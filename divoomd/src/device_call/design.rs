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
        "design.set_eq" | "set_eq" => {
            let dynamic = kw
                .and_then(|v| v.get("dynamic"))
                .and_then(|v| v.as_bool())
                .or_else(|| raw_args.first().and_then(|v| v.as_bool()))
                .unwrap_or(false);
            // R67/C7: `dynamic` is a bool at position 0, which the numeric list
            // drops — so args[1] was the SECOND number, not `mode`.
            let mode = crate::device_call::pos_i64(raw_args, 1, kw, "mode", 0) as u8;
            let stream = kw
                .and_then(|v| v.get("stream"))
                .and_then(|v| v.as_bool())
                .or_else(|| raw_args.get(2).and_then(|v| v.as_bool()))
                .unwrap_or(false);
            let payload = [0x1eu8, dynamic as u8, mode, stream as u8];
            match dev.send_command(0xbd, &payload, true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_eq failed: {e}")),
            }
        }
        "design.set_language" | "set_language" => {
            let lang = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("lang")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xbd, &[0x26, lang], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_language failed: {e}")),
            }
        }
        "design.set_user_define_time" | "set_user_define_time" => {
            let hour = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("hour")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let minute = args
                .get(1)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("minute")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            let second = args
                .get(2)
                .copied()
                .or_else(|| kw.and_then(|v| v.get("second")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev
                .send_command(0xbd, &[0x14, hour, minute, second], true)
                .await
            {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_user_define_time failed: {e}")),
            }
        }
        "design.get_user_define_time" | "get_user_define_time" => {
            match dev.send_command_and_wait(0xbd, &[0x15], timeout).await {
                Some(p) if p.len() >= 3 => json!({
                    "success": true,
                    "result": {
                        "hour": p[0] as i64,
                        "minute": p[1] as i64,
                        "second": p[2] as i64,
                    }
                }),
                Some(p) if p.len() == 2 => json!({
                    "success": true,
                    "result": {
                        "hour": p[0] as i64,
                        "minute": p[1] as i64,
                        "second": 0,
                    }
                }),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "design.set_screen_dir" | "set_screen_dir" => {
            let direction = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("direction")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xbd, &[0x23, direction], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_screen_dir failed: {e}")),
            }
        }
        "design.set_screen_mirror" | "set_screen_mirror" => {
            let on = kw
                .and_then(|v| v.get("on"))
                .and_then(|v| v.as_bool())
                .or_else(|| kw.and_then(|v| v.get("enabled")).and_then(|v| v.as_bool()))
                .or_else(|| raw_args.first().and_then(|v| v.as_bool()))
                .unwrap_or(false);
            match dev.send_command(0xbd, &[0x24, on as u8], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("set_screen_mirror failed: {e}")),
            }
        }
        "design.factory_reset" | "factory_reset" => {
            match dev.send_command(0xbd, &[0x25, 0x01], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("factory_reset failed: {e}")),
            }
        }
        "design.use_user_define_index" | "use_user_define_index" => {
            let page = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("page")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xbd, &[0x17, page], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("use_user_define_index failed: {e}")),
            }
        }
        "design.clear_user_define_index" | "clear_user_define_index" => {
            let page = args
                .first()
                .copied()
                .or_else(|| kw.and_then(|v| v.get("page")).and_then(|v| v.as_i64()))
                .unwrap_or(0) as u8;
            match dev.send_command(0xbd, &[0x16, page], true).await {
                Ok(()) => json!({"success": true, "result": true}),
                Err(e) => err_reply(&format!("clear_user_define_index failed: {e}")),
            }
        }
        _ => err_reply("unimplemented design command"),
    }
}
