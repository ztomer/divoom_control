//! The temperature family of `system.*`: the device's own reading, the
//! network temperature it displays, and the unit. Split from `system.rs` at
//! the file-length cap; the arms in `system::handle` name these directly.

use crate::device_call::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

pub(super) async fn get_device_temp(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let timeout = ctx.timeout;

    match dev.send_command_and_wait(0x59, &[], timeout).await {
        Some(p) if p.len() >= 2 => json!({
            "success": true,
            "result": {
                "format": i64::from(p[0]),
                "value": i64::from(i8::from_ne_bytes([p[1]])),
            }
        }),
        _ => json!({"success": true, "result": Value::Null}),
    }
}

pub(super) async fn send_net_temp(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

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
                    // Saturate into the field width: a caller asking
                    // for 300 degrees used to wrap to 44 on the wire.
                    let temp_val = pair[0].as_i64().unwrap_or(0).byte();
                    let weather_type = pair[1].as_i64().unwrap_or(0).byte();
                    payload.push(temp_val);
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

pub(super) async fn send_net_temp_disp(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    let display_modes = raw_args
        .first()
        .or_else(|| kw.and_then(|v| v.get("display_modes")))
        .and_then(|v| v.as_array());
    // R67/C7: `display_modes` is a LIST, which the numeric list drops,
    // so args[1] was past the end and a positional time_minutes was
    // always lost. It sits at true position 1.
    let time_minutes = crate::device_call::pos_i64(raw_args, 1, kw, "time_minutes", 0).word();

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

pub(super) async fn get_net_temp_disp(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let timeout = ctx.timeout;

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

pub(super) async fn send_current_temp(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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
        .unwrap_or(0)
        .byte();
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
    match dev.send_command(0x5f, &[temp, weather], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("send_current_temp failed: {e}")),
    }
}

pub(super) async fn set_temp_type(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

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
