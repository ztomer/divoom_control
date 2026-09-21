use super::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    match method {
        "timeplan.set_time_manage_info" | "set_time_manage_info" => set_time_manage_info(ctx).await,
        "timeplan.set_time_manage_ctrl" | "set_time_manage_ctrl" => set_time_manage_ctrl(ctx).await,
        _ => err_reply("unimplemented timeplan command"),
    }
}
async fn set_time_manage_info(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;
    // Every numeric field: the keyword, else its positional slot, else 0.
    let field = |name: &str, slot: usize| {
        kw.and_then(|v| v.get(name))
            .and_then(serde_json::Value::as_i64)
            .or_else(|| args.get(slot).copied())
            .unwrap_or(0)
            .byte()
    };

    let status = field("status", 0);
    let hour = field("hour", 1);
    let minute = field("minute", 2);
    let week = field("week", 3);
    let mode = field("mode", 4);
    let trigger_mode = field("trigger_mode", 5);
    let fm_freq = kw
        .and_then(|v| v.get("fm_freq"))
        .and_then(serde_json::Value::as_i64)
        .or_else(|| args.get(6).copied())
        .unwrap_or(0)
        .word();
    let volume = field("volume", 7);
    let tp_type = field("type", 8);

    let mut payload = Vec::with_capacity(10);
    payload.push(status);
    payload.push(hour);
    payload.push(minute);
    payload.push(week);
    payload.push(mode);
    payload.push(trigger_mode);
    payload.extend_from_slice(&fm_freq.to_le_bytes());
    payload.push(volume);
    payload.push(tp_type);

    if tp_type == 0 {
        let animation_id = field("animation_id", 9);
        let animation_speed = field("animation_speed", 10);
        let animation_direction = field("animation_direction", 11);
        let animation_frame_count = field("animation_frame_count", 12);
        let animation_frame_delay = field("animation_frame_delay", 13);
        let animation_frame_data: Vec<u8> = raw_args
            .get(14)
            .and_then(|v| v.as_array())
            .or_else(|| {
                kw.and_then(|v| v.get("animation_frame_data"))
                    .and_then(|v| v.as_array())
            })
            .map(|a| {
                a.iter()
                    .filter_map(|x| x.as_u64().map(super::super::wire::WireNarrow::byte))
                    .collect()
            })
            .unwrap_or_default();

        payload.push(animation_id);
        payload.push(animation_speed);
        payload.push(animation_direction);
        payload.push(animation_frame_count);
        payload.push(animation_frame_delay);
        payload.extend_from_slice(&animation_frame_data);
    }

    match dev.send_command(0x56, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_time_manage_info failed: {e}")),
    }
}

async fn set_time_manage_ctrl(ctx: CallCtx<'_>) -> Value {
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
    let index = args
        .get(1)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("index"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    match dev.send_command(0x57, &[status, index], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_time_manage_ctrl failed: {e}")),
    }
}
