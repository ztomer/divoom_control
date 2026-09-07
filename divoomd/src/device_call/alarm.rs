use super::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;
    let timeout = ctx.timeout;

    match method {
        "alarm.get_alarm_time" | "get_alarm_time" => {
            match dev.send_command_and_wait(0x42, &[], timeout).await {
                Some(p) => {
                    let record_len = 10;
                    let count = std::cmp::min(10, p.len() / record_len);
                    let mut alarms = Vec::with_capacity(count);
                    for i in 0..count {
                        let start = i * record_len;
                        let block = &p[start..start + record_len];
                        alarms.push(json!({
                            "status": i64::from(block[1]),
                            "hour": i64::from(block[2]),
                            "minute": i64::from(block[3]),
                            "week": i64::from(block[4]),
                            "mode": i64::from(block[5]),
                            "trigger_mode": i64::from(block[6]),
                            "fm_freq": i64::from(u16::from_le_bytes([block[7], block[8]])),
                            "volume": i64::from(block[9]),
                        }));
                    }
                    json!({"success": true, "result": alarms})
                }
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "alarm.set_alarm" | "set_alarm" => {
            let alarm_index = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("alarm_index"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let status = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("status"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let hour = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("hour"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let minute = args
                .get(3)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("minute"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let week = args
                .get(4)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("week"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let mode = args
                .get(5)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("mode"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let trigger_mode = args
                .get(6)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("trigger_mode"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let fm_freq = args
                .get(7)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("fm_freq"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .word();
            let volume = args
                .get(8)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("volume"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();

            let mut payload = Vec::with_capacity(10);
            payload.push(alarm_index);
            payload.push(status);
            payload.push(hour);
            payload.push(minute);
            payload.push(week);
            payload.push(mode);
            payload.push(trigger_mode);
            payload.extend_from_slice(&fm_freq.to_le_bytes());
            payload.push(volume);

            match dev.send_command(0x43, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_alarm failed: {e}")),
            }
        }
        "alarm.set_alarm_gif" | "set_alarm_gif" => {
            let alarm_index = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("alarm_index"))
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
            payload.push(alarm_index);
            payload.extend_from_slice(&total_length.to_le_bytes());
            payload.push(gif_id);
            payload.extend_from_slice(&data);

            match dev.send_command(0x51, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_alarm_gif failed: {e}")),
            }
        }
        "alarm.get_memorial_time" | "get_memorial_time" => {
            match dev.send_command_and_wait(0x53, &[], timeout).await {
                Some(p) => {
                    let record_len = 39;
                    let count = std::cmp::min(10, p.len() / record_len);
                    let mut memorials = Vec::with_capacity(count);
                    for i in 0..count {
                        let start = i * record_len;
                        let block = &p[start..start + record_len];
                        let title = String::from_utf8_lossy(&block[7..39])
                            .trim_end_matches('\0')
                            .to_string();
                        memorials.push(json!({
                            "dialy_id": i64::from(block[0]),
                            "on_off": i64::from(block[1]),
                            "month": i64::from(block[2]),
                            "day": i64::from(block[3]),
                            "hour": i64::from(block[4]),
                            "minute": i64::from(block[5]),
                            "have_flag": i64::from(block[6]),
                            "title_name": title,
                        }));
                    }
                    json!({"success": true, "result": memorials})
                }
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "alarm.set_memorial_time" | "set_memorial_time" => {
            let dialy_id = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("dialy_id"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let on_off = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("on_off"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let month = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("month"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let day = args
                .get(3)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("day"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let hour = args
                .get(4)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("hour"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let minute = args
                .get(5)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("minute"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let have_flag = args
                .get(6)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("have_flag"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let title_name = raw_args
                .get(7)
                .and_then(|v| v.as_str())
                .or_else(|| {
                    kw.and_then(|v| v.get("title_name"))
                        .and_then(|v| v.as_str())
                })
                .unwrap_or("");

            let mut title_bytes = title_name.as_bytes().to_vec();
            if title_bytes.len() > 32 {
                title_bytes.truncate(32);
            }
            while title_bytes.len() < 32 {
                title_bytes.push(0);
            }

            let mut payload = Vec::with_capacity(39);
            payload.push(dialy_id);
            payload.push(on_off);
            payload.push(month);
            payload.push(day);
            payload.push(hour);
            payload.push(minute);
            payload.push(have_flag);
            payload.extend_from_slice(&title_bytes);

            match dev.send_command(0x54, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_memorial_time failed: {e}")),
            }
        }
        "alarm.set_memorial_gif" | "set_memorial_gif" => {
            let memorial_index = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("memorial_index"))
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
            payload.push(memorial_index);
            payload.extend_from_slice(&total_length.to_le_bytes());
            payload.push(gif_id);
            payload.extend_from_slice(&data);

            match dev.send_command(0x55, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_memorial_gif failed: {e}")),
            }
        }
        "alarm.set_alarm_listen" | "set_alarm_listen" => {
            let on_off = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("on_off"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let mode = args
                .get(1)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("mode"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            let volume = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("volume"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            match dev.send_command(0xa5, &[on_off, mode, volume], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_alarm_listen failed: {e}")),
            }
        }
        "alarm.set_alarm_volume" | "set_alarm_volume" => {
            let volume = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("volume"))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(0)
                .byte();
            match dev.send_command(0xa6, &[volume], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_alarm_volume failed: {e}")),
            }
        }
        "alarm.set_alarm_volume_control" | "set_alarm_volume_control" => {
            let control = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("control"))
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
            match dev.send_command(0x82, &[control, index], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_alarm_volume_control failed: {e}")),
            }
        }
        _ => err_reply("unimplemented alarm command"),
    }
}
