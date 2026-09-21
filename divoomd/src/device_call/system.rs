mod temp;

use super::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

/// # Panics
///
/// If the mutex guarding this value is poisoned -- another thread panicked
/// while holding it, so the value cannot be trusted.
pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    match method {
        "time.set_hour_type" | "set_hour_type" | "system.set_hour_type" => set_hour_type(ctx).await,
        // Sync the device clock. Ported from divoom_lib/system/date_time.py
        // (DateTimeCommand): command 0x18, payload
        //   [year%100, year//100, month, day, hour, minute, second, 0x00].
        // The caller supplies local-time components (year, month, day, hour,
        // minute, second) positionally or as kwargs.
        "system.set_date_time" | "set_date_time" | "sync_time" | "time.set_date_time" => {
            set_date_time(ctx).await
        }
        "bluetooth.set_bluetooth_password"
        | "set_bluetooth_password"
        | "system.set_bluetooth_password" => set_bluetooth_password(ctx).await,
        "device.get_work_mode" | "system.get_work_mode" | "get_work_mode" => {
            get_work_mode(ctx).await
        }
        "device.set_work_mode" | "system.set_work_mode" | "set_work_mode" => {
            set_work_mode(ctx).await
        }
        // control.set_light_mode is the same single-byte 0x45 channel select.
        "system.set_channel" | "set_channel" | "device.set_channel" | "control.set_light_mode" => {
            set_channel(ctx).await
        }
        // Control.set_hot (0x26): enable/disable hot mode.
        "control.set_hot" | "set_hot" => set_hot(ctx).await,
        // Control.set_keyboard (0x23): single Ditoo key press.
        "control.set_keyboard" | "set_keyboard" => set_keyboard(ctx).await,
        "system.send_sd_status" | "send_sd_status" | "device.send_sd_status" => {
            send_sd_status(ctx).await
        }
        "system.get_device_temp" | "get_device_temp" | "device.get_device_temp" => {
            temp::get_device_temp(ctx).await
        }
        "system.send_net_temp" | "send_net_temp" | "device.send_net_temp" => {
            temp::send_net_temp(ctx).await
        }
        "system.send_net_temp_disp" | "send_net_temp_disp" | "device.send_net_temp_disp" => {
            temp::send_net_temp_disp(ctx).await
        }
        "system.get_net_temp_disp" | "get_net_temp_disp" | "device.get_net_temp_disp" => {
            temp::get_net_temp_disp(ctx).await
        }
        // weather.set(temp, weather_type) is the same 0x5f command (two's-complement
        // temp byte). set_temperature/set_weather are the stateful Python variants;
        // mapped here too (caller passes both args).
        "system.send_current_temp"
        | "send_current_temp"
        | "device.send_current_temp"
        | "weather.set"
        | "weather.set_temperature"
        | "weather.set_weather" => temp::send_current_temp(ctx).await,
        "system.set_temp_type" | "set_temp_type" | "device.set_temp_type" => {
            temp::set_temp_type(ctx).await
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
async fn set_hour_type(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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

async fn set_date_time(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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
        (year % 100).byte(),
        (year / 100).byte(),
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

async fn set_bluetooth_password(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

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
            // `to_digit(10)` returns 0..=9 by contract (and the
            // all-ascii-digit check above makes `unwrap` unreachable).
            payload.push(u8::try_from(c.to_digit(10).unwrap()).expect("decimal digit fits"));
        }
    }

    match dev.send_command(0x27, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_bluetooth_password failed: {e}")),
    }
}

async fn get_work_mode(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let timeout = ctx.timeout;

    match dev.send_command_and_wait(0x13, &[], timeout).await {
        Some(p) if !p.is_empty() => json!({"success": true, "result": i64::from(p[0])}),
        _ => json!({"success": true, "result": Value::Null}),
    }
}

async fn set_work_mode(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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

async fn set_channel(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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

async fn set_hot(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    // R67/C7: `args` drops non-numerics, and a JSON `true` is not an
    // i64 — so a positional set_hot(True) produced an EMPTY list, fell
    // through to a missing kwarg, and sent FALSE. Read the true index.
    let enabled = crate::device_call::pos_bool(raw_args, 0, kw, "enabled", false);
    match dev.send_command(0x26, &[u8::from(enabled)], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_hot failed: {e}")),
    }
}

async fn set_keyboard(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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

async fn send_sd_status(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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
