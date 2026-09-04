use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};
use std::time::Duration;

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    match method {
        "game.show_game" | "show_game" => {
            let value = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("value")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let payload = if value > 0 {
                [0x01, value]
            } else {
                [0x00, 0x00]
            };
            match dev.send_command(0xa0, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("show_game failed: {e}")),
            }
        }
        "game.hide_game" | "hide_game" | "game.exit_game" | "exit_game" => {
            match dev.send_command(0xa0, &[0x00, 0x00], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("hide_game/exit_game failed: {e}")),
            }
        }
        "game.set_key_down" | "set_key_down" => {
            let key = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("key")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x17, &[key], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_key_down failed: {e}")),
            }
        }
        "game.set_key_up" | "set_key_up" => {
            let key = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("key")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x21, &[key], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_key_up failed: {e}")),
            }
        }
        "game.set_magic_ball_answer" | "set_magic_ball_answer" => {
            let answer = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("answer")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0x88, &[answer], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_magic_ball_answer failed: {e}")),
            }
        }
        "game.send_gamecontrol" | "send_gamecontrol" => {
            let value_arg = raw_args.first().or_else(|| kw.and_then(|v| v.get("value")));

            let control_value = match value_arg {
                None => 0,
                Some(Value::String(s)) => match s.to_lowercase().as_str() {
                    "go" => 0,
                    "left" => 1,
                    "right" => 2,
                    "up" => 3,
                    "down" => 4,
                    "ok" => 5,
                    _ => 0,
                },
                Some(Value::Number(n)) => n.as_i64().unwrap_or(0) as u8,
                _ => 0,
            };

            if control_value == 0 {
                match dev.send_command(0x88, &[], true).await {
                    Ok(()) => json!({"success": true, "result": true}),
                    Err(e) => err_reply(&format!("send_gamecontrol (go) failed: {e}")),
                }
            } else {
                let down_ok = dev.send_command(0x17, &[control_value], true).await.is_ok();
                tokio::time::sleep(Duration::from_millis(100)).await;
                let up_ok = dev.send_command(0x21, &[control_value], true).await.is_ok();
                json!({"success": down_ok && up_ok, "result": down_ok && up_ok})
            }
        }
        _ => err_reply("unimplemented game command"),
    }
}
