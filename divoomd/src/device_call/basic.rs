use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

mod display;

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    // The `display.*`/`show_*` (0x45 channel payloads + image streaming) family
    // lives in `display.rs`; keep this dispatcher for the rest.
    if matches!(
        method,
        "device.show_clock"
            | "show_clock"
            | "device.show_image"
            | "show_image"
            | "display.show_image"
            | "display.display_image"
            | "display.show_clock"
            | "display.set_clock_rich"
            | "display.show_design"
            | "display.show_light"
            | "light.show_light"
            | "show_light"
            | "display.show_effects"
            | "show_effects"
            | "display.show_visualization"
            | "show_visualization"
            | "display.show_scoreboard"
            | "show_scoreboard"
            | "display.set_temperature_channel"
            | "set_temperature_channel"
            | "display.switch_channel"
            | "switch_channel"
    ) {
        return display::handle(method, ctx).await;
    }

    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;
    let timeout = ctx.timeout;

    match method {
        "system.get_device_name" | "device.get_device_name" | "get_device_name" => {
            if let Some(name) = dev.device_name() {
                if !name.trim().is_empty() {
                    return json!({"success": true, "result": name});
                }
            }
            match dev.send_command_and_wait(0x76, &[], timeout).await {
                Some(p) if !p.is_empty() => {
                    let name_len = p[0] as usize;
                    if p.len() > name_len {
                        let name_bytes = &p[1..1 + name_len];
                        match std::str::from_utf8(name_bytes) {
                            Ok(name) => {
                                dev.set_cached_device_name(name.to_string());
                                json!({"success": true, "result": name})
                            }
                            Err(_) => json!({"success": true, "result": Value::Null}),
                        }
                    } else {
                        json!({"success": true, "result": Value::Null})
                    }
                }
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "system.set_device_name" | "device.set_device_name" | "set_device_name" => {
            let name = raw_args
                .first()
                .and_then(|v| v.as_str())
                .or_else(|| kw.and_then(|v| v.get("name")).and_then(|v| v.as_str()))
                .unwrap_or("");
            let mut name_bytes = name.as_bytes().to_vec();
            if name_bytes.len() > 16 {
                name_bytes.truncate(16);
            }
            let mut payload = Vec::with_capacity(1 + name_bytes.len());
            payload.push(name_bytes.len() as u8);
            payload.extend_from_slice(&name_bytes);
            match dev.send_command(0x75, &payload, true).await {
                Ok(()) => {
                    if let Ok(utf8_name) = std::str::from_utf8(&name_bytes) {
                        dev.set_cached_device_name(utf8_name.to_string());
                    }
                    json!({"success": true, "result": true})
                }
                Err(e) => err_reply(&format!("set_device_name failed: {e}")),
            }
        }
        "system.get_brightness"
        | "device.get_brightness"
        | "get_brightness"
        | "display.get_brightness" => match dev.send_command_and_wait(0x46, &[], timeout).await {
            Some(p) if p.len() >= 7 => json!({"success": true, "result": p[6] as i64}),
            _ => json!({"success": true, "result": Value::Null}),
        },
        // Full 0x46 light-mode read-back (Python Light.get_light_mode; GLM offsets).
        "light.get_light_mode" | "get_light_mode" => {
            match dev.send_command_and_wait(0x46, &[], timeout).await {
                Some(r) if r.len() >= 20 => json!({"success": true, "result": {
                    "current_light_effect_mode": r[0],
                    "temperature_display_mode": r[1],
                    "vj_selection_option": r[2],
                    "rgb_color_values": [r[3], r[4], r[5]],
                    "brightness_level": r[6],
                    "lighting_mode_selection_option": r[7],
                    "on_off_switch": r[8],
                    "music_mode_selection_option": r[9],
                    "system_brightness": r[10],
                    "time_display_format_selection_option": r[11],
                    "time_display_rgb_color_values": [r[12], r[13], r[14]],
                    "time_display_mode": r[15],
                    "time_checkbox_modes": [r[16], r[17], r[18], r[19]],
                }}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "system.set_brightness"
        | "device.set_brightness"
        | "set_brightness"
        | "display.set_brightness" => {
            let val = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("brightness"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0)
                .clamp(0, 100) as u8;
            match dev.send_command(0x74, &[val], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_brightness failed: {e}")),
            }
        }
        // Switch to the cloud/hot channel (Python HotUpdate.show_hot_channel):
        // 0x45 [0x02], then optionally 0x85 [1, page] to select a page.
        "hot_update.show_hot_channel" | "show_hot_channel" => {
            if let Err(e) = dev.send_command(0x45, &[0x02], true).await {
                return err_reply(&format!("show_hot_channel: 0x45 failed: {e}"));
            }
            let page = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("page")).and_then(|v| v.as_i64()));
            if let Some(p) = page {
                match dev.send_command(0x85, &[1, p as u8], true).await {
                    Ok(()) => json!({"success": true, "result": true}),
                    Err(e) => err_reply(&format!("show_hot_channel: 0x85 failed: {e}")),
                }
            } else {
                json!({"success": true, "result": true})
            }
        }
        // hot_update.update routes to the existing top-level `hot_update` streamer
        // (art_hot.rs) so the device_call alias reuses the verified implementation.
        "hot_update.update" => {
            let device_size = kw
                .and_then(|v| v.get("device_size"))
                .and_then(|v| v.as_i64())
                .unwrap_or(16);
            let req = crate::protocol::Request {
                command: "hot_update".to_string(),
                args: json!({"device_size": device_size}),
                token: None,
            };
            Box::pin(ctx.daemon.dispatch(req)).await
        }
        "music.set_volume" | "set_volume" => {
            let val = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("volume")).and_then(|v| v.as_i64()))
                .unwrap_or(0)
                .clamp(0, 15) as u8;
            match dev.send_command(0x08, &[val], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_volume failed: {e}")),
            }
        }
        "music.get_volume" | "get_volume" => {
            match dev.send_command_and_wait(0x09, &[], timeout).await {
                Some(p) if !p.is_empty() => json!({"success": true, "result": p[0] as i64}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "radio.set_radio_frequency" | "set_radio_frequency" | "radio.set_radio" | "set_radio" => {
            let freq = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("frequency")).and_then(|v| v.as_i64()))
                .or_else(|| kw.and_then(|v| v.get("freq_x10")).and_then(|v| v.as_i64()))
                .unwrap_or(875) as u16;
            let payload = freq.to_le_bytes();
            match dev.send_command(0x61, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_radio_frequency failed: {e}")),
            }
        }
        "system.set_low_power_switch"
        | "device.set_low_power_switch"
        | "set_low_power_switch"
        | "device.set_low_power"
        | "set_low_power" => {
            let on_off_val = raw_args
                .first()
                .or_else(|| kw.and_then(|v| v.get("on_off")))
                .or_else(|| kw.and_then(|v| v.get("enabled")));
            let on_off = match on_off_val {
                Some(Value::Bool(b)) => {
                    if *b {
                        1
                    } else {
                        0
                    }
                }
                Some(Value::Number(n)) => n.as_i64().unwrap_or(0).clamp(0, 1) as u8,
                _ => args.first().copied().unwrap_or(0).clamp(0, 1) as u8,
            };
            match dev.send_command(0xb2, &[on_off], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_low_power_switch failed: {e}")),
            }
        }
        "system.get_low_power_switch"
        | "device.get_low_power_switch"
        | "get_low_power_switch"
        | "device.get_low_power"
        | "get_low_power" => match dev.send_command_and_wait(0xb3, &[], timeout).await {
            Some(p) if !p.is_empty() => json!({"success": true, "result": p[0] as i64}),
            _ => json!({"success": true, "result": Value::Null}),
        },
        "system.set_auto_power_off"
        | "device.set_auto_power_off"
        | "set_auto_power_off"
        | "sound.set_auto_power_off" => {
            let minutes = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("minutes")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u16;
            let payload = minutes.to_le_bytes();
            match dev.send_command(0xab, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_auto_power_off failed: {e}")),
            }
        }
        "system.get_auto_power_off"
        | "device.get_auto_power_off"
        | "get_auto_power_off"
        | "sound.get_auto_power_off" => match dev.send_command_and_wait(0xac, &[], timeout).await {
            Some(p) if p.len() >= 2 => {
                let minutes = u16::from_le_bytes([p[0], p[1]]) as i64;
                json!({"success": true, "result": minutes})
            }
            _ => json!({"success": true, "result": Value::Null}),
        },
        "animation.stream_animation_8b" => {
            let blob: Vec<u8> = if let Some(data) = ctx.blob_map.lock().unwrap().remove(&0) {
                data
            } else {
                match kw.and_then(|m| m.get("blob")).and_then(|v| v.as_array()) {
                    Some(a) => a
                        .iter()
                        .filter_map(|x| x.as_u64().map(|n| n as u8))
                        .collect(),
                    None => return err_reply("animation.stream_animation_8b requires 'blob'"),
                }
            };
            match dev.stream_animation_8b(&blob).await {
                Ok(true) => json!({"success": true, "result": true}),
                Ok(false) => err_reply("stream_animation_8b: empty blob"),
                Err(e) => err_reply(&format!("stream_animation_8b failed: {e}")),
            }
        }
        _ => err_reply("unimplemented basic command"),
    }
}
