use super::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_possible_wrap,
    clippy::cast_sign_loss,
    reason = "a device command dispatcher: every value here comes from a caller's JSON and is written into a protocol field of fixed width. The ones that could be out of range go through `wire::WireNarrow`; these are indices, enum discriminants and already-bounded counts"
)]
/// # Panics
///
/// If the mutex guarding this value is poisoned -- another thread panicked
/// while holding it, so the value cannot be trusted.
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
                .or_else(|| {
                    kw.and_then(|v| v.get("hour_type"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
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
                    .or_else(|| {
                        kw.and_then(|v| v.get(k))
                            .and_then(serde_json::Value::as_i64)
                    })
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
                || kw.is_some_and(|m| {
                    ["year", "month", "day", "hour", "minute", "second"]
                        .iter()
                        .any(|k| m.contains_key(*k))
                });
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
                month.byte(),
                day.byte(),
                hour.byte(),
                minute.byte(),
                second.byte(),
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
                .or_else(|| {
                    kw.and_then(|v| v.get("control"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
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
                Some(p) if !p.is_empty() => json!({"success": true, "result": i64::from(p[0])}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "device.set_work_mode" | "system.set_work_mode" | "set_work_mode" => {
            let mode = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("mode"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
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
                        .and_then(serde_json::Value::as_i64)
                })
                .or_else(|| {
                    kw.and_then(|v| v.get("channel"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
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
            match dev.send_command(0x26, &[u8::from(enabled)], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_hot failed: {e}")),
            }
        }
        // Control.set_keyboard (0x23): single Ditoo key press.
        "control.set_keyboard" | "set_keyboard" => {
            let key = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("key"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            match dev.send_command(0x23, &[key], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_keyboard failed: {e}")),
            }
        }
        "system.send_sd_status" | "send_sd_status" | "device.send_sd_status" => {
            let status = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("status"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
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
                        "format": i64::from(p[0]),
                        "value": i64::from(p[1] as i8),
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "system.send_net_temp" | "send_net_temp" | "device.send_net_temp" => {
            let year = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("year"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(2026)
                .word();
            let month = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("month"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(1)
                .byte();
            let day = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("day"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(1)
                .byte();
            let hour = args
                .get(3)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("hour"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let minute = args
                .get(4)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("minute"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let num = args
                .get(5)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("num"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();

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
                            let weather_type = pair[1].as_i64().unwrap_or(0).byte();
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
                crate::device_call::pos_i64(raw_args, 1, kw, "time_minutes", 0).word();

            let mut payload = Vec::new();
            if let Some(arr) = display_modes {
                for mode_val in arr.iter().take(5) {
                    let mode_byte = match mode_val {
                        Value::Bool(b) => u8::from(*b),
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
                        "display_modes": [i64::from(p[0]), i64::from(p[1]), i64::from(p[2]), i64::from(p[3]), i64::from(p[4])],
                        "time_minutes": i64::from(u16::from_le_bytes([p[5], p[6]])),
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
                .or_else(|| {
                    kw.and_then(|v| v.get("temp"))
                        .and_then(serde_json::Value::as_i64)
                })
                .or_else(|| {
                    kw.and_then(|v| v.get("temperature"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0) as i8;
            let weather = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("weather"))
                        .and_then(serde_json::Value::as_i64)
                })
                .or_else(|| {
                    kw.and_then(|v| v.get("weather_type"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            match dev.send_command(0x5f, &[temp as u8, weather], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("send_current_temp failed: {e}")),
            }
        }
        "system.set_temp_type" | "set_temp_type" | "device.set_temp_type" => {
            let temp_type = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("temp_type"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            match dev.send_command(0x2b, &[temp_type], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_temp_type failed: {e}")),
            }
        }
        _ => {
            // `sound.*` lives in its own module; anything it does not
            // claim falls through to the one unimplemented answer.
            if let Some(v) = super::system_sound::handle(method, ctx).await {
                return v;
            }
            err_reply("unimplemented system command")
        }
    }
}
