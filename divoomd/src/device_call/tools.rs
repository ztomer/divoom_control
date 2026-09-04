use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    match method {
        "scoreboard.set_scoreboard" | "set_scoreboard" => {
            let on_off = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("on_off")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let red_score = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("red_score")).and_then(|v| v.as_i64()))
                .unwrap_or(0)
                .clamp(0, 999) as u16;
            let blue_score = args
                .get(2)
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("blue_score"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0)
                .clamp(0, 999) as u16;
            let mut payload = Vec::with_capacity(6);
            payload.push(1u8); // TOOL_TYPE_SCORE
            payload.push(on_off);
            payload.extend_from_slice(&red_score.to_le_bytes());
            payload.extend_from_slice(&blue_score.to_le_bytes());
            match dev.send_command(0x72, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_scoreboard failed: {e}")),
            }
        }
        "scoreboard.get_scoreboard" | "get_scoreboard" => {
            match dev.send_command_and_wait(0x71, &[1], ctx.timeout).await {
                Some(p) if p.len() >= 5 => json!({
                    "success": true,
                    "result": {
                        "on_off": p[0] as i64,
                        "red_score": u16::from_le_bytes([p[1], p[2]]) as i64,
                        "blue_score": u16::from_le_bytes([p[3], p[4]]) as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "timer.set_timer" | "set_timer" => {
            let ctrl_flag = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("ctrl_flag")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let payload = [0u8, ctrl_flag]; // TOOL_TYPE_TIMER = 0
            match dev.send_command(0x72, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_timer failed: {e}")),
            }
        }
        "timer.get_timer" | "get_timer" => {
            match dev.send_command_and_wait(0x71, &[0], ctx.timeout).await {
                Some(p) if !p.is_empty() => json!({
                    "success": true,
                    "result": {
                        "status": p[0] as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "countdown.set_countdown" | "set_countdown" => {
            let ctrl_flag = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("ctrl_flag")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let minutes = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("minutes")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let seconds = args
                .get(2)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("seconds")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let payload = [3u8, ctrl_flag, minutes, seconds]; // TOOL_TYPE_COUNTDOWN = 3
            match dev.send_command(0x72, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_countdown failed: {e}")),
            }
        }
        "countdown.get_countdown" | "get_countdown" => {
            match dev.send_command_and_wait(0x71, &[3], ctx.timeout).await {
                Some(p) if p.len() >= 3 => json!({
                    "success": true,
                    "result": {
                        "status": p[0] as i64,
                        "minutes": p[1] as i64,
                        "seconds": p[2] as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "noise.set_noise" | "set_noise" => {
            let ctrl_flag = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("ctrl_flag")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let payload = [2u8, ctrl_flag]; // TOOL_TYPE_NOISE = 2
            match dev.send_command(0x72, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_noise failed: {e}")),
            }
        }
        "noise.get_noise" | "get_noise" => {
            match dev.send_command_and_wait(0x71, &[2], ctx.timeout).await {
                Some(p) if !p.is_empty() => json!({
                    "success": true,
                    "result": {
                        "status": p[0] as i64,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "device.show_notification" | "show_notification" | "notification.show_notification" => {
            let app_type = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("app_type")).and_then(|v| v.as_i64()))
                .unwrap_or(1) as u8;
            let wire = if app_type >= 8 {
                app_type + 1
            } else {
                app_type
            };
            match dev.send_command(0x50, &[wire], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("show_notification failed: {e}")),
            }
        }
        "device.show_notification_text"
        | "show_notification_text"
        | "notification.show_notification_text" => {
            let app_type = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("app_type")).and_then(|v| v.as_i64()))
                .unwrap_or(1) as u8;
            let text = raw_args
                .get(1)
                .and_then(|v| v.as_str())
                .or_else(|| kw.and_then(|v| v.get("text")).and_then(|v| v.as_str()))
                .unwrap_or("");
            let mut text_bytes = text.as_bytes().to_vec();
            if text_bytes.len() > 128 {
                text_bytes.truncate(128);
            }
            let mut payload = Vec::with_capacity(2 + text_bytes.len());
            payload.push(app_type);
            payload.push(text_bytes.len() as u8);
            payload.extend_from_slice(&text_bytes);
            match dev.send_command(0x50, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("show_notification_text failed: {e}")),
            }
        }
        // Generic tool read-back (Python Tool.get_tool_info): 0x71 [tool_type] →
        // parse per type (GTI offsets). Types: 0=timer 1=score 2=noise 3=countdown.
        "tool.get_tool_info" | "get_tool_info" => {
            let tool_type = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("tool_type")).and_then(|v| v.as_i64()))
                .unwrap_or(0);
            match dev
                .send_command_and_wait(0x71, &[tool_type as u8], ctx.timeout)
                .await
            {
                Some(r) => {
                    let result = match tool_type {
                        0 if !r.is_empty() => json!({"status": r[0] as i64}),
                        1 if r.len() >= 5 => json!({
                            "on_off": r[0] as i64,
                            "red_score": u16::from_le_bytes([r[1], r[2]]) as i64,
                            "blue_score": u16::from_le_bytes([r[3], r[4]]) as i64,
                        }),
                        2 if !r.is_empty() => json!({"status": r[0] as i64}),
                        3 if r.len() >= 3 => json!({
                            "status": r[0] as i64, "minutes": r[1] as i64, "seconds": r[2] as i64,
                        }),
                        255 => json!({"status": "not in game mode"}),
                        _ => Value::Null,
                    };
                    json!({"success": true, "result": result})
                }
                None => json!({"success": true, "result": Value::Null}),
            }
        }
        // Generic tool setter (Python Tool.set_tool_info): 0x72 [game_mode_index,
        // *per-type args]. 0=timer[ctrl_flag] 1=score[on_off, red LE16, blue LE16]
        // 2=noise[ctrl_flag] 3=countdown[ctrl_flag, minutes, seconds].
        "tool.set_tool_info" | "set_tool_info" => {
            let gmi = args
                .first()
                .copied()
                .or_else(|| {
                    kw.and_then(|v| v.get("game_mode_index"))
                        .and_then(|v| v.as_i64())
                })
                .unwrap_or(0);
            let g = |n: &str| kw.and_then(|v| v.get(n)).and_then(|v| v.as_i64());
            let mut payload = vec![gmi as u8];
            match gmi {
                0 | 2 => match g("ctrl_flag") {
                    Some(c) => payload.push(c as u8),
                    None => return err_reply("set_tool_info: timer/noise need 'ctrl_flag'"),
                },
                1 => match g("on_off") {
                    Some(on_off) => {
                        payload.push(on_off as u8);
                        payload
                            .extend_from_slice(&(g("red_score").unwrap_or(0) as u16).to_le_bytes());
                        payload.extend_from_slice(
                            &(g("blue_score").unwrap_or(0) as u16).to_le_bytes(),
                        );
                    }
                    None => return err_reply("set_tool_info: score needs 'on_off'"),
                },
                3 => match (g("ctrl_flag"), g("minutes"), g("seconds")) {
                    (Some(c), Some(m), Some(s)) => {
                        payload.push(c as u8);
                        payload.push(m as u8);
                        payload.push(s as u8);
                    }
                    _ => {
                        return err_reply(
                            "set_tool_info: countdown needs ctrl_flag/minutes/seconds",
                        )
                    }
                },
                _ => return err_reply(&format!("set_tool_info: unknown game_mode_index {gmi}")),
            }
            match dev.send_command(0x72, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_tool_info failed: {e}")),
            }
        }
        _ => err_reply("unimplemented tools command"),
    }
}
