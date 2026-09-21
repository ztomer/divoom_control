//! The `sound.*` half of the system command surface.
//!
//! Split out of `system` for the house 500-line cap, along a seam that names
//! itself: every arm here is a `sound.*` method and its aliases, and none of
//! them touches the time, temperature or channel state the rest of that
//! dispatcher works with.

use super::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

/// Handle one `sound.*` method, or `None` when it is not one of ours.
///
/// `None` rather than an error reply so the caller keeps ONE "unimplemented"
/// answer: two dispatchers each with their own fallback would disagree about
/// which unknown methods are unknown.
pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Option<Value> {
    Some(match method {
        "sound.set_song_display_control"
        | "system.set_song_display_control"
        | "set_song_display_control"
        | "device.set_song_display_control" => set_song_display_control(ctx).await,
        "sound.set_power_on_voice_volume"
        | "system.set_power_on_voice_volume"
        | "set_power_on_voice_volume"
        | "device.set_power_on_voice_volume" => set_power_on_voice_volume(ctx).await,
        "system.set_power_on_channel" | "device.set_power_on_channel" => {
            set_power_on_channel(ctx).await
        }
        "system.set_boot_gif" | "device.set_boot_gif" => set_boot_gif(ctx).await,
        "sound.set_sound_control"
        | "system.set_sound_control"
        | "set_sound_control"
        | "device.set_sound_control" => set_sound_control(ctx).await,
        "sound.get_sound_control"
        | "system.get_sound_control"
        | "get_sound_control"
        | "device.get_sound_control" => get_sound_control(ctx).await,
        _ => return None,
    })
}
async fn set_song_display_control(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
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
    match dev.send_command(0x83, &[control], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_song_display_control failed: {e}")),
    }
}

async fn set_power_on_voice_volume(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
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
    let volume = args
        .get(1)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("volume"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
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

async fn set_power_on_channel(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
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
    let channel_id = args
        .get(1)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("channel_id"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
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

async fn set_boot_gif(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;
    let raw_args = ctx.raw_args;

    let on_off = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("on_off"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let total_length = args
        .get(1)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("total_length"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .word();
    let gif_id = args
        .get(2)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("gif_id"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let data: Vec<u8> = raw_args
        .get(3)
        .and_then(|v| v.as_array())
        .or_else(|| kw.and_then(|v| v.get("data")).and_then(|v| v.as_array()))
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_u64().map(super::super::wire::WireNarrow::byte))
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

async fn set_sound_control(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let enable = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("enable"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    match dev.send_command(0xa7, &[enable], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_sound_control failed: {e}")),
    }
}

async fn get_sound_control(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let timeout = ctx.timeout;

    match dev.send_command_and_wait(0xa8, &[], timeout).await {
        Some(p) if !p.is_empty() => json!({"success": true, "result": i64::from(p[0])}),
        _ => json!({"success": true, "result": Value::Null}),
    }
}
