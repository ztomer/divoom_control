//! `display.*`/`show_*` device_call family (0x45 channel payloads + image
//! streaming). Pulled out of basic.rs to keep both files under the 500-LOC
//! ground rule.

use super::CallCtx;
use crate::packets::{ClockPacket, LightPacket, LightingType, CMD_SET_LIGHT_MODE};
use crate::protocol::err_reply;
use serde_json::{json, Value};

pub(super) async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    match method {
        // R67/C1: this arm used to hardcode 24h, humidity, weather, date AND the
        // colour, so the wall path (`t.show_clock(clock=style)`) silently
        // discarded the user's colour. It now reads the same fields as its
        // `display.` sibling, through the one shared packet.
        "device.show_clock" | "show_clock" => {
            let p = clock_packet_from_call(args, raw_args, kw);
            match dev
                .send_command(CMD_SET_LIGHT_MODE, &p.to_bytes(), true)
                .await
            {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("show_clock failed: {e}")),
            }
        }
        "device.show_image" | "show_image" => {
            let w = get_kwarg_i64(kw, "w", 16) as i32;
            let h = get_kwarg_i64(kw, "h", 16) as i32;
            let time_ms = get_kwarg_i64(kw, "time_ms", 100) as u16;
            let rgb: Vec<u8> = match kw.and_then(|m| m.get("rgb")).and_then(|v| v.as_array()) {
                Some(a) => a
                    .iter()
                    .filter_map(|x| x.as_u64().map(|n| n as u8))
                    .collect(),
                None => return err_reply("show_image requires 'rgb' (array of u8)"),
            };
            let expected = (w * h * 3) as usize;
            if rgb.len() != expected {
                return err_reply(&format!(
                    "show_image: rgb.len()={} expected w*h*3={expected}",
                    rgb.len()
                ));
            }
            let enc = match ctx.daemon.encoder() {
                Some(e) => e,
                None => return err_reply("encoder not available"),
            };
            let blob = match enc.encode_animation_frame(&rgb, w, h, time_ms) {
                Some(b) => b,
                None => return err_reply("encode_animation_frame failed"),
            };
            match dev.stream_animation_8b(&blob).await {
                Ok(true) => json!({"success": true, "result": true}),
                Ok(false) => err_reply("stream_animation_8b: empty blob"),
                Err(e) => err_reply(&format!("stream_animation_8b failed: {e}")),
            }
        }
        "display.show_image" | "display.display_image" => {
            let size = kw
                .and_then(|v| v.get("size"))
                .and_then(|v| v.as_u64())
                .unwrap_or(16) as u32;
            let default_time_ms = raw_args.get(1).and_then(|v| v.as_u64()).unwrap_or(100) as u16;

            let img_data: Vec<u8> = if let Some(data) = ctx.blob_map.lock().unwrap().remove(&0) {
                data
            } else {
                let path = match raw_args.first().and_then(|v| v.as_str()) {
                    Some(p) => p,
                    None => return err_reply("display.show_image requires a path or blob[0]"),
                };
                match std::fs::read(path) {
                    Ok(d) => d,
                    Err(e) => return err_reply(&format!("display.show_image: read {path}: {e}")),
                }
            };

            if let Err(e) = dev
                .send_command(
                    CMD_SET_LIGHT_MODE,
                    &crate::packets::channel_switch(crate::packets::Channel::Design),
                    false,
                )
                .await
            {
                return err_reply(&format!("show_design failed: {e}"));
            }

            let frames = match tokio::task::spawn_blocking(move || {
                crate::image_proc::process_image_bytes(img_data, size, default_time_ms)
            })
            .await
            {
                Ok(Ok(f)) => f,
                Ok(Err(e)) => return err_reply(&format!("image decode: {e}")),
                Err(e) => return err_reply(&format!("image decode task: {e}")),
            };

            let enc = match ctx.daemon.encoder() {
                Some(e) => e,
                None => return err_reply("encoder not available (DIVOOMD_ENCODER_LIB)"),
            };
            let mut blob = Vec::new();
            for (rgb, w, h, t) in &frames {
                let frame_body = if *w == 32 && *h == 32 {
                    enc.encode_animation_frame_32(rgb, *w, *h, *t)
                } else {
                    enc.encode_animation_frame(rgb, *w, *h, *t)
                };
                match frame_body {
                    Some(b) => blob.extend_from_slice(&b),
                    None => {
                        return err_reply(&format!("encode_animation_frame failed (frame {w}x{h})"))
                    }
                }
            }

            match dev.stream_animation_8b(&blob).await {
                Ok(true) => json!({"success": true, "result": true}),
                Ok(false) => err_reply("stream_animation_8b: empty blob"),
                Err(e) => err_reply(&format!("stream_animation_8b failed: {e}")),
            }
        }
        // R67/C1: this arm read kwargs named weather/temp/calendar and wrote
        // them into bytes 4/5/6 — but the canonical order (Python's builder,
        // from the APK's C2()) is humidity/weather/date. Asking for weather
        // therefore turned on HUMIDITY, and `humidity=` was not even accepted.
        // Both the names and the slots now come from ClockPacket.
        "display.show_clock" => {
            let p = clock_packet_from_call(args, raw_args, kw);
            match dev
                .send_command(CMD_SET_LIGHT_MODE, &p.to_bytes(), true)
                .await
            {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.show_clock failed: {e}")),
            }
        }
        "display.set_clock_rich" => {
            let p = clock_packet_from_call(args, raw_args, kw);
            match dev
                .send_command(CMD_SET_LIGHT_MODE, &p.to_bytes(), true)
                .await
            {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.set_clock_rich failed: {e}")),
            }
        }
        "display.show_design" => {
            match dev
                .send_command(
                    CMD_SET_LIGHT_MODE,
                    &crate::packets::channel_switch(crate::packets::Channel::Design),
                    false,
                )
                .await
            {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.show_design failed: {e}")),
            }
        }
        // R67/C1: the lighting-type byte was hardcoded to 0x00 here, so all five
        // ambient modes sent identical Plain-Colour packets while every RPC
        // returned success. `power` was also read only from kwargs, never from
        // positional index 2 — it defaulted to true and happened to be right.
        // Python's signature is show_light(color, brightness, power, lightning_type)
        // and DaemonDeviceProxy forwards those positionally, so both are read
        // positionally-or-by-keyword now.
        "display.show_light" | "light.show_light" | "show_light" => {
            // R67/C7: brightness used to read `args.get(1)` — the COMPACTED
            // numeric list, which for ("#00FFCC", 80, true, 2) is [80, 2]. So
            // index 1 was the MODE, and the ambient brightness slider silently
            // sent the mode number instead (mode 0 meant brightness 0). Found
            // by the wire trace on real hardware; no test could see it.
            let rgb = color_from_arg(raw_args, kw).unwrap_or([0xFF, 0xFF, 0xFF]);
            let brightness =
                crate::device_call::pos_i64(raw_args, 1, kw, "brightness", 100).clamp(0, 100) as u8;
            let power = crate::device_call::pos_bool(raw_args, 2, kw, "power", true);
            let kind = LightingType::from_i64(
                raw_args
                    .get(3)
                    .and_then(|v| v.as_i64())
                    .or_else(|| {
                        kw.and_then(|v| v.get("lightning_type"))
                            .and_then(|v| v.as_i64())
                    })
                    .or_else(|| kw.and_then(|v| v.get("mode_type")).and_then(|v| v.as_i64()))
                    .unwrap_or(0),
            );
            let payload = LightPacket {
                rgb,
                brightness,
                kind,
                power,
            }
            .to_bytes();
            match dev.send_command(0x45, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.show_light failed: {e}")),
            }
        }
        // VJ effects (1-indexed on BLE): 0x45 [0x03, number+1, 0×8] (Python show_effects).
        "display.show_effects" | "show_effects" => {
            let number = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("number")).and_then(|v| v.as_i64()))
                .unwrap_or(0);
            let payload = crate::packets::vj_effect(number.clamp(0, 254) as u8);
            match dev.send_command(0x45, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.show_effects failed: {e}")),
            }
        }
        // Visualization channel: 0x45 [0x04, number, 0×8] (Python show_visualization).
        "display.show_visualization" | "show_visualization" => {
            let number = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("number")).and_then(|v| v.as_i64()))
                .unwrap_or(0);
            let payload = crate::packets::visualization(number.clamp(0, 255) as u8);
            match dev.send_command(0x45, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.show_visualization failed: {e}")),
            }
        }
        // Scoreboard channel: 0x45 [0x06, 0×9] (Python show_scoreboard).
        "display.show_scoreboard" | "show_scoreboard" => {
            let payload = crate::packets::channel_switch(crate::packets::Channel::Scoreboard);
            match dev.send_command(0x45, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.show_scoreboard failed: {e}")),
            }
        }
        // Temperature channel: 0x45 [0x01, temp_type, r, g, b, 0x00] (Python set_temperature_channel).
        "display.set_temperature_channel" | "set_temperature_channel" => {
            let celsius = kw
                .and_then(|v| v.get("celsius"))
                .and_then(|v| v.as_bool())
                .unwrap_or(true);
            let [r, g, b] = kw
                .and_then(|v| v.get("color"))
                .and_then(|v| v.as_str())
                .and_then(parse_hex_color)
                .or_else(|| color_from_arg(raw_args, kw))
                .unwrap_or([0xFF, 0xFF, 0xFF]);
            let temp_type = if celsius { 0u8 } else { 1u8 };
            let payload = [0x01u8, temp_type, r, g, b, 0x00];
            match dev.send_command(0x45, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.set_temperature_channel failed: {e}")),
            }
        }
        // Channel switch by name → the matching 0x45 channel payload (Python switch_channel).
        "display.switch_channel" | "switch_channel" => {
            let channel = raw_args
                .first()
                .and_then(|v| v.as_str())
                .or_else(|| kw.and_then(|v| v.get("channel")).and_then(|v| v.as_str()))
                .unwrap_or("")
                .to_lowercase();
            let payload: [u8; 10] = match channel.as_str() {
                "clock" => [0x00, 1, 0, 1, 0, 0, 0, 0xFF, 0xFF, 0xFF],
                "visualizer" => [0x04, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                "vj" => [0x03, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                "design" => [0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                "scoreboard" => [0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                other => return err_reply(&format!("switch_channel: unknown channel '{other}'")),
            };
            match dev.send_command(0x45, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("display.switch_channel failed: {e}")),
            }
        }
        _ => err_reply("unimplemented display command"),
    }
}

/// Build a `ClockPacket` from a device_call's positional + keyword arguments.
///
/// R67/C1: three arms used to parse these fields independently, with different
/// kwarg names and different slot assignments. One parser, one packet, one
/// source of truth for the wire layout — a caller can no longer land `weather`
/// in the humidity slot because it never chooses a slot.
///
/// `clock` and `style` are accepted as aliases for the face index: Python has
/// `show_clock(clock=...)` and `set_clock_rich(style=...)` for the same field.
fn clock_packet_from_call(
    args: &[i64],
    raw_args: &[Value],
    kw: Option<&serde_json::Map<String, Value>>,
) -> ClockPacket {
    let kwb = |name: &str, default: bool| -> bool {
        kw.and_then(|v| v.get(name))
            .and_then(|v| v.as_bool())
            .unwrap_or(default)
    };
    let style = kw
        .and_then(|v| v.get("clock"))
        .and_then(|v| v.as_i64())
        .or_else(|| kw.and_then(|v| v.get("style")).and_then(|v| v.as_i64()))
        .or_else(|| args.first().copied())
        .unwrap_or(0)
        .clamp(0, 15) as u8;
    let rgb = kw
        .and_then(|v| v.get("color"))
        .and_then(|v| v.as_str())
        .and_then(parse_hex_color)
        .or_else(|| {
            raw_args
                .get(1)
                .and_then(|v| v.as_str())
                .and_then(parse_hex_color)
        })
        .unwrap_or([0xFF, 0xFF, 0xFF]);
    ClockPacket {
        env: 0,
        twentyfour: kwb("twentyfour", true),
        style,
        active: true,
        humidity: kwb("humidity", false),
        weather: kwb("weather", false),
        date: kwb("date", false),
        rgb,
    }
}

fn get_kwarg_i64(kw: Option<&serde_json::Map<String, Value>>, name: &str, default: i64) -> i64 {
    kw.and_then(|m| m.get(name))
        .and_then(|v| v.as_i64())
        .unwrap_or(default)
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

fn color_from_arg(
    raw_args: &[Value],
    kw: Option<&serde_json::Map<String, Value>>,
) -> Option<[u8; 3]> {
    let color_val = raw_args
        .first()
        .or_else(|| kw.and_then(|v| v.get("color")))?;
    if let Some(arr) = color_val.as_array() {
        let ns: Vec<u8> = arr
            .iter()
            .filter_map(|x| x.as_u64().map(|n| n as u8))
            .collect();
        if ns.len() >= 3 {
            return Some([ns[0], ns[1], ns[2]]);
        }
    }
    if let Some(s) = color_val.as_str() {
        return parse_hex_color(s);
    }
    None
}
