use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    match method {
        "sleep.show_sleep" | "show_sleep" => {
            let sleeptime = kw
                .and_then(|v| v.get("sleeptime"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.first().copied())
                .unwrap_or(60) as u8;
            let sleepmode = kw
                .and_then(|v| v.get("sleepmode"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(1).copied())
                .unwrap_or(0) as u8;
            let on = kw
                .and_then(|v| v.get("on"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(2).copied())
                .unwrap_or(1) as u8;
            let frequency = kw
                .and_then(|v| v.get("frequency"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(3).copied())
                .unwrap_or(0) as u16;
            let volume = kw
                .and_then(|v| v.get("volume"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(4).copied())
                .unwrap_or(16) as u8;
            let color_val = kw.and_then(|v| v.get("color")).or_else(|| raw_args.get(5));
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
            let brightness = kw
                .and_then(|v| v.get("brightness"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(6).copied())
                .unwrap_or(100) as u8;

            let mut payload = Vec::with_capacity(10);
            payload.push(sleeptime);
            payload.push(sleepmode);
            payload.push(on);
            payload.extend_from_slice(&frequency.to_le_bytes());
            payload.push(volume);
            payload.push(r);
            payload.push(g);
            payload.push(b);
            payload.push(brightness);

            match dev.send_command(0x40, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("show_sleep failed: {e}")),
            }
        }
        "sleep.get_sleep_scene" | "get_sleep_scene" => {
            match dev.send_command_and_wait(0xa2, &[], ctx.timeout).await {
                Some(p) if p.len() >= 10 => json!({
                    "success": true,
                    "result": {
                        "time": p[0] as i64,
                        "mode": p[1] as i64,
                        "on": p[2] as i64,
                        "fm_freq": u16::from_le_bytes([p[3], p[4]]) as i64,
                        "volume": p[5] as i64,
                        "color_r": p[6] as i64,
                        "color_g": p[7] as i64,
                        "color_b": p[8] as i64,
                        "light": p[9] as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "sleep.set_sleep_scene_listen" | "set_sleep_scene_listen" => {
            let on_off = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("on_off")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let mode = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("mode")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let volume = args
                .get(2)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("volume")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xa3, &[on_off, mode, volume], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_sleep_scene_listen failed: {e}")),
            }
        }
        "sleep.set_scene_volume" | "set_scene_volume" => {
            let volume = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("volume")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xa4, &[volume], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_scene_volume failed: {e}")),
            }
        }
        "sound.set_sleep_color" | "sleep.set_sleep_color" | "set_sleep_color" => {
            let color_val = raw_args.first().or_else(|| kw.and_then(|v| v.get("color")));
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
            match dev.send_command(0xad, &[r, g, b], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_sleep_color failed: {e}")),
            }
        }
        "sleep.set_sleep_light" | "set_sleep_light" => {
            let light = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("light")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xae, &[light], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_sleep_light failed: {e}")),
            }
        }
        "sleep.set_sleep_scene" | "set_sleep_scene" => {
            let mode = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("mode")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let on = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("on")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let fm_freq: Vec<u8> = raw_args
                .get(2)
                .and_then(|v| v.as_array())
                .or_else(|| kw.and_then(|v| v.get("fm_freq")).and_then(|v| v.as_array()))
                .map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_u64().map(|n| n as u8))
                        .collect()
                })
                .unwrap_or_else(|| vec![0, 0]);
            let fm_freq = if fm_freq.len() >= 2 {
                fm_freq
            } else {
                vec![0, 0]
            };
            let volume = args
                .get(3)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("volume")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let color_val = raw_args.get(4).or_else(|| kw.and_then(|v| v.get("color")));
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
            let light = args
                .get(5)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("light")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;

            let mut payload = Vec::with_capacity(9);
            payload.push(mode);
            payload.push(on);
            payload.extend_from_slice(&fm_freq[0..2]);
            payload.push(volume);
            payload.push(r);
            payload.push(g);
            payload.push(b);
            payload.push(light);

            match dev.send_command(0x41, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_sleep_scene failed: {e}")),
            }
        }
        _ => err_reply("unimplemented sleep command"),
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
