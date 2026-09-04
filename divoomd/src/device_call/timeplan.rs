use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    match method {
        "timeplan.set_time_manage_info" | "set_time_manage_info" => {
            let status = kw
                .and_then(|v| v.get("status"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.first().copied())
                .unwrap_or(0) as u8;
            let hour = kw
                .and_then(|v| v.get("hour"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(1).copied())
                .unwrap_or(0) as u8;
            let minute = kw
                .and_then(|v| v.get("minute"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(2).copied())
                .unwrap_or(0) as u8;
            let week = kw
                .and_then(|v| v.get("week"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(3).copied())
                .unwrap_or(0) as u8;
            let mode = kw
                .and_then(|v| v.get("mode"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(4).copied())
                .unwrap_or(0) as u8;
            let trigger_mode = kw
                .and_then(|v| v.get("trigger_mode"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(5).copied())
                .unwrap_or(0) as u8;
            let fm_freq = kw
                .and_then(|v| v.get("fm_freq"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(6).copied())
                .unwrap_or(0) as u16;
            let volume = kw
                .and_then(|v| v.get("volume"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(7).copied())
                .unwrap_or(0) as u8;
            let tp_type = kw
                .and_then(|v| v.get("type"))
                .and_then(|v| v.as_i64())
                .or_else(|| args.get(8).copied())
                .unwrap_or(0) as u8;

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
                let animation_id = kw
                    .and_then(|v| v.get("animation_id"))
                    .and_then(|v| v.as_i64())
                    .or_else(|| args.get(9).copied())
                    .unwrap_or(0) as u8;
                let animation_speed = kw
                    .and_then(|v| v.get("animation_speed"))
                    .and_then(|v| v.as_i64())
                    .or_else(|| args.get(10).copied())
                    .unwrap_or(0) as u8;
                let animation_direction = kw
                    .and_then(|v| v.get("animation_direction"))
                    .and_then(|v| v.as_i64())
                    .or_else(|| args.get(11).copied())
                    .unwrap_or(0) as u8;
                let animation_frame_count = kw
                    .and_then(|v| v.get("animation_frame_count"))
                    .and_then(|v| v.as_i64())
                    .or_else(|| args.get(12).copied())
                    .unwrap_or(0) as u8;
                let animation_frame_delay = kw
                    .and_then(|v| v.get("animation_frame_delay"))
                    .and_then(|v| v.as_i64())
                    .or_else(|| args.get(13).copied())
                    .unwrap_or(0) as u8;
                let animation_frame_data: Vec<u8> = raw_args
                    .get(14)
                    .and_then(|v| v.as_array())
                    .or_else(|| {
                        kw.and_then(|v| v.get("animation_frame_data"))
                            .and_then(|v| v.as_array())
                    })
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_u64().map(|n| n as u8))
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
        "timeplan.set_time_manage_ctrl" | "set_time_manage_ctrl" => {
            let status = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("status")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let index = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("index")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x57, &[status, index], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_time_manage_ctrl failed: {e}")),
            }
        }
        _ => err_reply("unimplemented timeplan command"),
    }
}
