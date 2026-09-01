use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

/// Scrolling marquee text, ported from the APK's own sequence.
///
/// **R73.** The device has no font for arbitrary strings, which is why
/// `push_text` rasterises a static PNG instead: 0x87
/// (`SPP_LIEGHT_PHONE_GIF32_WORD_ATTR`) never rendered on these panels, and the
/// conclusion drawn at the time was that device-side text was a dead end. It
/// was not — it just needs the glyphs uploaded first. `CmdManager` does four
/// things, in this order:
///
/// 0. `SPP_DRAWING_CTRL_MOVIE_PLAY` (0x6E): `[1]` — start playback.
/// 1. `SPP_LED_UPDATE_FONT_INFO` (0x7C), one packet per **5 characters**:
///    `[total_chars, start_index, count]` then per char
///    `[cp_lo, cp_hi, glyph[32]]` — the UTF-16LE code unit followed by its
///    raw 16x16 1bpp bitmap.
/// 2. `SPP_SEND_LED_WORD_CMD` (0x86) sub 1: `[1, char_count, UTF-16LE bytes]`.
/// 4. `SPP_SEND_LED_WORD_CMD` (0x86) sub 0: `[0, rate]`.
///
/// **The order is load-bearing and not the intuitive one.** `f1(true)` (0x6E,
/// `SPP_DRAWING_CTRL_MOVIE_PLAY`) goes FIRST, before any content, and the rate
/// goes LAST. This shipped the readable way round -- content, then rate, then
/// start -- and a real Tivoo-Max displayed nothing at all: the panel enters
/// marquee mode after the string it was handed has already been consumed.
///
/// **Not supported by the Tivoo-Max, proven on the wire (R73).** Encoded
/// exactly as above and sent to a real device with `DIVOOMD_BLE_DEBUG`, in one
/// controlled window against a known-good command:
///
/// ```text
/// tx cmd=0x45 (show_light)  ->  basic frame cmd=0x45     <- device acks
/// tx cmd=0x6e               ->  (nothing)
/// tx cmd=0x7c               ->  (nothing)
/// tx cmd=0x86  x2           ->  (nothing)
/// ```
///
/// The panel acks a command it implements and returns NOTHING for these, so
/// its firmware does not carry the LED-word command set. The A/B matters: an
/// earlier run showed no RX either, but so did a window with no traffic at all
/// -- absence of a reply only means something next to a reply that did arrive.
///
/// The bytes on the wire were verified correct in that same trace (`0x7c` =
/// `02 00 02` then `48 00` for 'H' and its glyph; `0x86` = `01 02 48 00 49 00`
/// for "HI"), so this is a firmware gap, not an encoding bug.
///
/// Kept, with no GUI surface, because the decode is complete and correct and
/// another model may well implement it -- only the Tivoo-Max was reachable.
/// Do NOT wire a button to it without retesting: a control that does nothing
/// is what R73 spent its length removing.
///
/// The glyphs come from the same `divoom_fond16_*` blob family the APK ships
/// and this daemon already embeds, so the bytes are reused verbatim.
async fn scrolling_text(ctx: &CallCtx<'_>) -> Value {
    use crate::live_jobs::render::device_glyph_bytes;

    let dev = ctx.dev;
    let kw = ctx.kwargs;
    let text = match kw
        .and_then(|v| v.get("text"))
        .and_then(|v| v.as_str())
        .filter(|t| !t.trim().is_empty())
    {
        Some(t) => t,
        None => return err_reply("show_scrolling_text requires a non-empty `text`"),
    };

    // UTF-16LE code units, which is both what the device is sent and what the
    // glyph table is keyed by. Chars outside the BMP would need surrogate
    // handling the APK does not do either, so they are refused rather than
    // silently mangled into two bogus glyphs.
    let units: Vec<u16> = text.encode_utf16().collect();
    if text.chars().any(|c| (c as u32) > 0xFFFF) {
        return err_reply("show_scrolling_text: characters outside the BMP are not supported");
    }
    if units.len() > 255 {
        return err_reply(&format!(
            "show_scrolling_text: {} characters exceeds the 255 the length byte can carry",
            units.len()
        ));
    }
    let rate = kw
        .and_then(|v| v.get("rate"))
        .and_then(|v| v.as_i64())
        .unwrap_or(50)
        .clamp(1, 255) as u8;

    // 0. start playback FIRST. CmdManager.G() is explicit about the order:
    //    f1(true) -> z1(text) [glyphs, then the string] -> B1(rate). Sending
    //    the start LAST reads more naturally and is what this first shipped
    //    with; on a real Tivoo-Max it rendered nothing, because the device
    //    enters marquee mode after the content it was given is already gone.
    if let Err(e) = dev.send_command(0x6E, &[1u8], true).await {
        return err_reply(&format!(
            "show_scrolling_text: starting playback failed: {e}"
        ));
    }

    // 1. glyph upload, 5 characters per packet
    let total = units.len() as u8;
    for (chunk_idx, chunk) in units.chunks(5).enumerate() {
        let mut p = Vec::with_capacity(3 + chunk.len() * 34);
        p.push(total);
        p.push((chunk_idx * 5) as u8);
        p.push(chunk.len() as u8);
        for &u in chunk {
            p.push((u & 0xFF) as u8);
            p.push((u >> 8) as u8);
            match device_glyph_bytes(u as u32) {
                Some(g) => p.extend_from_slice(g),
                None => return err_reply("show_scrolling_text: the font blob has no usable glyph"),
            }
        }
        if let Err(e) = dev.send_command(0x7C, &p, true).await {
            return err_reply(&format!("show_scrolling_text: glyph upload failed: {e}"));
        }
    }

    // 2. the string itself
    let mut p = Vec::with_capacity(2 + units.len() * 2);
    p.push(1u8);
    p.push(total);
    for &u in &units {
        p.push((u & 0xFF) as u8);
        p.push((u >> 8) as u8);
    }
    if let Err(e) = dev.send_command(0x86, &p, true).await {
        return err_reply(&format!(
            "show_scrolling_text: sending the text failed: {e}"
        ));
    }

    // 3. rate LAST, matching B1(rate) at the end of CmdManager.G().
    if let Err(e) = dev.send_command(0x86, &[0u8, rate], true).await {
        return err_reply(&format!(
            "show_scrolling_text: setting the rate failed: {e}"
        ));
    }
    json!({"success": true, "result": true, "characters": units.len(), "rate": rate})
}

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    if method.ends_with("show_scrolling_text") || method.ends_with("scrolling_text") {
        return scrolling_text(&ctx).await;
    }
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    let is_content_only = method.ends_with("set_text_content");
    let control = if is_content_only {
        6
    } else {
        args.first()
            .copied()
            .or_else(|| kw.and_then(|v| v.get("control")).and_then(|v| v.as_i64()))
            .unwrap_or(6) as u8
    };

    let mut payload = Vec::new();
    payload.push(control);

    match control {
        1 => {
            // Speed
            let speed = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("speed")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u16;
            let text_box_id = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("text_box_id"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            payload.extend_from_slice(&speed.to_le_bytes());
            payload.push(text_box_id);
        }
        2 => {
            // Effects
            let effect_style = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("effect_style"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            payload.push(effect_style);
        }
        3 => {
            // Display Box
            let x = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("x")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let y = args
                .get(2)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("y")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let width = args
                .get(3)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("width")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let height = args
                .get(4)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("height")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let text_box_id = args
                .get(5)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("text_box_id"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            payload.push(x);
            payload.push(y);
            payload.push(width);
            payload.push(height);
            payload.push(text_box_id);
        }
        4 => {
            // Font
            let font_size = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("font_size")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let text_box_id = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("text_box_id"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            payload.push(font_size);
            payload.push(text_box_id);
        }
        5 => {
            // Color
            let color_val = raw_args.get(1).or_else(|| kw.and_then(|v| v.get("color")));
            let [r, g, b] = if let Some(cv) = color_val {
                if let Some(arr) = cv.as_array() {
                    let ns: Vec<u8> = arr
                        .iter()
                        .filter_map(|x| x.as_u64().map(|n| n as u8))
                        .collect();
                    if ns.len() >= 3 {
                        [ns[0], ns[1], ns[2]]
                    } else {
                        [255, 255, 255]
                    }
                } else if let Some(s) = cv.as_str() {
                    parse_hex_color(s).unwrap_or([255, 255, 255])
                } else {
                    [255, 255, 255]
                }
            } else {
                [255, 255, 255]
            };
            let text_box_id = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("text_box_id"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            payload.push(r);
            payload.push(g);
            payload.push(b);
            payload.push(text_box_id);
        }
        6 => {
            // Content
            let content_val = if is_content_only {
                raw_args
                    .first()
                    .or_else(|| kw.and_then(|v| v.get("text_content")))
                    .or_else(|| kw.and_then(|v| v.get("text")))
            } else {
                raw_args
                    .get(1)
                    .or_else(|| kw.and_then(|v| v.get("text_content")))
                    .or_else(|| kw.and_then(|v| v.get("text")))
            };
            let content = content_val.and_then(|v| v.as_str()).unwrap_or("");
            let text_box_id = if is_content_only {
                args.get(1)
                    .copied()
                    .or_else(|| {
                        kw.and_then(|v| v.get("text_box_id"))
                            .and_then(|v| v.as_i64())
                    })
                    .unwrap_or(0) as u8
            } else {
                args.get(2)
                    .copied()
                    .or_else(|| {
                        kw.and_then(|v| v.get("text_box_id"))
                            .and_then(|v| v.as_i64())
                    })
                    .unwrap_or(0) as u8
            };
            let content_bytes = content.as_bytes();
            let len = content_bytes.len() as u16;
            payload.extend_from_slice(&len.to_le_bytes());
            payload.extend_from_slice(content_bytes);
            payload.push(text_box_id);
        }
        7 => {
            // Image Effects
            let effect_style = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("effect_style"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            let text_box_id = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("text_box_id"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            payload.push(effect_style);
            payload.push(text_box_id);
        }
        other => {
            return err_reply(&format!(
                "Unknown control word for set_light_phone_word_attr: {other}"
            ))
        }
    }

    match dev.send_command(0x87, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_light_phone_word_attr failed: {e}")),
    }
}

fn parse_hex_color(s: &str) -> Option<[u8; 3]> {
    let s = s.trim_start_matches('#');
    if s.len() == 6 {
        let r = u8::from_str_radix(&s[0..2], 16).ok()?;
        let g = u8::from_str_radix(&s[2..4], 16).ok()?;
        let b = u8::from_str_radix(&s[4..6], 16).ok()?;
        Some([r, g, b])
    } else {
        None
    }
}
