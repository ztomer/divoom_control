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
            // R67/C7: these indices were read from the COMPACTED numeric list
            // and did not match the Python signature in either order or
            // position. `show_sleep` is
            //   (value, sleeptime, sleepmode, volume, color, brightness,
            //    frequency, on)
            //      0        1          2         3      4        5
            //                                                    6      7
            // so `color` is at 4 (it was read from 5) and every numeric was off
            // as soon as the caller passed `value` or `color` positionally.
            // Keyword callers were always fine, which is why this survived.
            use crate::device_call::pos_i64;
            let sleeptime = pos_i64(raw_args, 1, kw, "sleeptime", 60) as u8;
            let sleepmode = pos_i64(raw_args, 2, kw, "sleepmode", 0) as u8;
            let volume = pos_i64(raw_args, 3, kw, "volume", 16) as u8;
            let frequency = pos_i64(raw_args, 6, kw, "frequency", 0) as u16;
            let on = pos_i64(raw_args, 7, kw, "on", 1) as u8;
            let color_val = kw.and_then(|v| v.get("color")).or_else(|| raw_args.get(4));
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
            let brightness = pos_i64(raw_args, 5, kw, "brightness", 100) as u8;

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
            // R67/C7: fm_freq and color are LISTS, which the numeric list
            // drops — so `volume` (true position 3) was read as the 4th NUMBER
            // (which is `light`), and `light` fell off the end entirely.
            // Signature: (mode, on, fm_freq, volume, color, light).
            use crate::device_call::pos_i64;
            let mode = pos_i64(raw_args, 0, kw, "mode", 0) as u8;
            let on = pos_i64(raw_args, 1, kw, "on", 0) as u8;
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
            let volume = pos_i64(raw_args, 3, kw, "volume", 0) as u8;
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
            let light = pos_i64(raw_args, 5, kw, "light", 0) as u8;

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
