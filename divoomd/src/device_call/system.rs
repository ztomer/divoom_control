use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;
    let timeout = ctx.timeout;

    match method {
        "time.set_hour_type" | "set_hour_type" | "system.set_hour_type" => {
            let hour_type = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("hour_type")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x2c, &[hour_type], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_hour_type failed: {e}")),
            }
        }
        // Sync the device clock. Ported from divoom_lib/system/date_time.py
        // (DateTimeCommand): command 0x18, payload
        //   [year%100, year//100, month, day, hour, minute, second, 0x00].
        // The caller supplies local-time components (year, month, day, hour,
        // minute, second) positionally or as kwargs.
        "system.set_date_time" | "set_date_time" | "sync_time" | "time.set_date_time" => {
            let g = |i: usize, k: &str, d: i64| {
                args.get(i)
                    .copied()
                    .or_else(|| kw.and_then(|v| v.get(k)).and_then(|v| v.as_i64()))
                    .unwrap_or(d)
            };
            // R72 P1.2: refuse a call that supplies no time at all.
            //
            // The defaults below are 2000-01-01 00:00:00, and one of this
            // command's aliases is `sync_time` -- so `sync_time` with no
            // arguments silently set the device clock to the year 2000 while
            // reporting success. A command that cannot do what its name says
            // must refuse, not quietly do something else.
            //
            // The daemon does NOT read the wall clock itself: converting epoch
            // seconds to local calendar time needs a timezone database, and
            // pulling in chrono to avoid passing six integers would be the
            // expensive way to fix a non-problem. The client owns the calendar
            // values (they are user intent, in the user's timezone); the daemon
            // owns the PACKET, which is what the duplicate was really about.
            let supplied = !args.is_empty()
                || kw
                    .map(|m| {
                        ["year", "month", "day", "hour", "minute", "second"]
                            .iter()
                            .any(|k| m.contains_key(*k))
                    })
                    .unwrap_or(false);
            if !supplied {
                return err_reply(
                    "set_date_time needs the time: pass year/month/day/hour/minute/second \
                     (with none supplied this would set the device to 2000-01-01)",
                );
            }
            let year = g(0, "year", 2000);
            let month = g(1, "month", 1);
            let day = g(2, "day", 1);
            let hour = g(3, "hour", 0);
            let minute = g(4, "minute", 0);
            let second = g(5, "second", 0);
            let payload = [
                (year % 100) as u8,
                (year / 100) as u8,
                month as u8,
                day as u8,
                hour as u8,
                minute as u8,
                second as u8,
                0x00,
            ];
            match dev.send_command(0x18, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_date_time failed: {e}")),
            }
        }
        "bluetooth.set_bluetooth_password"
        | "set_bluetooth_password"
        | "system.set_bluetooth_password" => {
            let control = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("control")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let password = raw_args
                .get(1)
                .and_then(|v| v.as_str())
                .or_else(|| kw.and_then(|v| v.get("password")).and_then(|v| v.as_str()))
                .unwrap_or("");

            let mut payload = Vec::new();
            payload.push(control);

            if control == 1 {
                if password.len() != 4 || !password.chars().all(|c| c.is_ascii_digit()) {
                    return err_reply("Password must be a 4-digit string");
                }
                for c in password.chars() {
                    payload.push(c.to_digit(10).unwrap() as u8);
                }
            }

            match dev.send_command(0x27, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_bluetooth_password failed: {e}")),
            }
        }
        "device.get_work_mode" | "system.get_work_mode" | "get_work_mode" => {
            match dev.send_command_and_wait(0x13, &[], timeout).await {
                Some(p) if !p.is_empty() => json!({"success": true, "result": p[0] as i64}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "device.set_work_mode" | "system.set_work_mode" | "set_work_mode" => {
            let mode = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("mode")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x05, &[mode], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_work_mode failed: {e}")),
            }
        }
        // control.set_light_mode is the same single-byte 0x45 channel select.
        "system.set_channel" | "set_channel" | "device.set_channel" | "control.set_light_mode" => {
            let channel_id = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("channel_id"))
                        .and_then(|v| v.as_i64())
                })
                .or_else(|| kw.and_then(|v| v.get("channel")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x45, &[channel_id], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_channel failed: {e}")),
            }
        }
        // Control.set_hot (0x26): enable/disable hot mode.
        "control.set_hot" | "set_hot" => {
            // R67/C7: `args` drops non-numerics, and a JSON `true` is not an
            // i64 — so a positional set_hot(True) produced an EMPTY list, fell
            // through to a missing kwarg, and sent FALSE. Read the true index.
            let enabled = crate::device_call::pos_bool(raw_args, 0, kw, "enabled", false);
            match dev.send_command(0x26, &[enabled as u8], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_hot failed: {e}")),
            }
        }
        // Control.set_keyboard (0x23): single Ditoo key press.
        "control.set_keyboard" | "set_keyboard" => {
            let key = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("key")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x23, &[key], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_keyboard failed: {e}")),
            }
        }
        "system.send_sd_status" | "send_sd_status" | "device.send_sd_status" => {
            let status = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("status")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x15, &[status], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("send_sd_status failed: {e}")),
            }
        }
        "system.get_device_temp" | "get_device_temp" | "device.get_device_temp" => {
            match dev.send_command_and_wait(0x59, &[], timeout).await {
                Some(p) if p.len() >= 2 => json!({
                    "success": true,
                    "result": {
                        "format": p[0] as i64,
                        "value": p[1] as i8 as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "system.send_net_temp" | "send_net_temp" | "device.send_net_temp" => {
            let year = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("year")).and_then(|v| v.as_i64()))
                .unwrap_or(2026) as u16;
            let month = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("month")).and_then(|v| v.as_i64()))
                .unwrap_or(1) as u8;
            let day = args
                .get(2)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("day")).and_then(|v| v.as_i64()))
                .unwrap_or(1) as u8;
            let hour = args
                .get(3)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("hour")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let minute = args
                .get(4)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("minute")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let num = args
                .get(5)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("num")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;

            let mut payload = Vec::new();
            payload.extend_from_slice(&year.to_le_bytes());
            payload.push(month);
            payload.push(day);
            payload.push(hour);
            payload.push(minute);
            payload.push(num);

            let temp_data = raw_args
                .get(6)
                .or_else(|| kw.and_then(|v| v.get("temp_data")))
                .and_then(|v| v.as_array());

            if let Some(arr) = temp_data {
                for item in arr {
                    if let Some(pair) = item.as_array() {
                        if pair.len() >= 2 {
                            let temp_val = pair[0].as_i64().unwrap_or(0) as i8;
                            let weather_type = pair[1].as_i64().unwrap_or(0) as u8;
                            payload.push(temp_val as u8);
                            payload.push(weather_type);
                        }
                    }
                }
            }

            match dev.send_command(0x5d, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("send_net_temp failed: {e}")),
            }
        }
        "system.send_net_temp_disp" | "send_net_temp_disp" | "device.send_net_temp_disp" => {
            let display_modes = raw_args
                .first()
                .or_else(|| kw.and_then(|v| v.get("display_modes")))
                .and_then(|v| v.as_array());
            // R67/C7: `display_modes` is a LIST, which the numeric list drops,
            // so args[1] was past the end and a positional time_minutes was
            // always lost. It sits at true position 1.
            let time_minutes =
                crate::device_call::pos_i64(raw_args, 1, kw, "time_minutes", 0) as u16;

            let mut payload = Vec::new();
            if let Some(arr) = display_modes {
                for mode_val in arr.iter().take(5) {
                    let mode_byte = match mode_val {
                        Value::Bool(b) => {
                            if *b {
                                1
                            } else {
                                0
                            }
                        }
                        Value::Number(n) if n.as_i64().unwrap_or(0) != 0 => 1,
                        _ => 0,
                    };
                    payload.push(mode_byte);
                }
            }
            while payload.len() < 5 {
                payload.push(0);
            }
            payload.extend_from_slice(&time_minutes.to_le_bytes());

            match dev.send_command(0x5e, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("send_net_temp_disp failed: {e}")),
            }
        }
        "system.get_net_temp_disp" | "get_net_temp_disp" | "device.get_net_temp_disp" => {
            match dev.send_command_and_wait(0x73, &[], timeout).await {
                Some(p) if p.len() >= 7 => json!({
                    "success": true,
                    "result": {
                        "display_modes": [p[0] as i64, p[1] as i64, p[2] as i64, p[3] as i64, p[4] as i64],
                        "time_minutes": u16::from_le_bytes([p[5], p[6]]) as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        // weather.set(temp, weather_type) is the same 0x5f command (two's-complement
        // temp byte). set_temperature/set_weather are the stateful Python variants;
        // mapped here too (caller passes both args).
        "system.send_current_temp"
        | "send_current_temp"
        | "device.send_current_temp"
        | "weather.set"
        | "weather.set_temperature"
        | "weather.set_weather" => {
            let temp = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("temp")).and_then(|v| v.as_i64()))
                .or_else(|| {
                    kw.and_then(|v| v.get("temperature"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as i8;
            let weather = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("weather")).and_then(|v| v.as_i64()))
                .or_else(|| {
                    kw.and_then(|v| v.get("weather_type"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            match dev.send_command(0x5f, &[temp as u8, weather], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("send_current_temp failed: {e}")),
            }
        }
        "system.set_temp_type" | "set_temp_type" | "device.set_temp_type" => {
            let temp_type = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("temp_type")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x2b, &[temp_type], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_temp_type failed: {e}")),
            }
        }
        "sound.set_song_display_control"
        | "system.set_song_display_control"
        | "set_song_display_control"
        | "device.set_song_display_control" => {
            let control = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("control")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x83, &[control], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_song_display_control failed: {e}")),
            }
        }
        "sound.set_power_on_voice_volume"
        | "system.set_power_on_voice_volume"
        | "set_power_on_voice_volume"
        | "device.set_power_on_voice_volume" => {
            let control = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("control")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let volume = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("volume")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let payload = if control == 1 {
                vec![control, volume]
            } else {
                vec![control]
            };
            match dev.send_command(0xbb, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_power_on_voice_volume failed: {e}")),
            }
        }
        "system.set_power_on_channel" | "device.set_power_on_channel" => {
            let control = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("control")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let channel_id = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("channel_id"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u8;
            let payload = if control == 1 {
                vec![control, channel_id]
            } else {
                vec![control]
            };
            match dev.send_command(0x8a, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_power_on_channel failed: {e}")),
            }
        }
        "system.set_boot_gif" | "device.set_boot_gif" => {
            let on_off = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("on_off")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let total_length = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("total_length"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0) as u16;
            let gif_id = args
                .get(2)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("gif_id")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let data: Vec<u8> = raw_args
                .get(3)
                .and_then(|v| v.as_array())
                .or_else(|| kw.and_then(|v| v.get("data")).and_then(|v| v.as_array()))
                .map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_u64().map(|n| n as u8))
                        .collect()
                })
                .unwrap_or_default();

            let mut payload = Vec::with_capacity(4 + data.len());
            payload.push(on_off);
            payload.extend_from_slice(&total_length.to_le_bytes());
            payload.push(gif_id);
            payload.extend_from_slice(&data);

            match dev.send_command(0x52, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_boot_gif failed: {e}")),
            }
        }
        "sound.set_sound_control"
        | "system.set_sound_control"
        | "set_sound_control"
        | "device.set_sound_control" => {
            let enable = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("enable")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xa7, &[enable], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_sound_control failed: {e}")),
            }
        }
        "sound.get_sound_control"
        | "system.get_sound_control"
        | "get_sound_control"
        | "device.get_sound_control" => match dev.send_command_and_wait(0xa8, &[], timeout).await {
            Some(p) if !p.is_empty() => json!({"success": true, "result": p[0] as i64}),
            _ => json!({"success": true, "result": Value::Null}),
        },
        _ => err_reply("unimplemented system command"),
    }
}
