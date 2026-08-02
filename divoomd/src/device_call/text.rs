use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
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
