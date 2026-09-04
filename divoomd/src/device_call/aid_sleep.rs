//! AidSleep BLE commands (play/add/delete/exit) — SPP_JSON over BLE, no
//! cloud call needed (see divoom_lib/tools/aid_sleep.py, the Python
//! counterpart this mirrors). Confirmed wire-framing match to the decompiled
//! APK's `bluetooth.q#B()`: command_id=1, JSON-serialized command object as
//! the payload. Browsing the catalog (AidSleep/GetAllList — cloud, RC=3 fix
//! documented in cloud_category.rs) is a separate, already-implemented path.

use super::CallCtx;
use crate::protocol::err_reply;
use serde_json::{json, Value};

const SPP_JSON_COMMAND_ID: u8 = 1;

async fn send_json_command(
    ctx: &CallCtx<'_>,
    command: &str,
    mut fields: serde_json::Map<String, Value>,
) -> Value {
    fields.insert("Command".to_string(), json!(command));
    let body = Value::Object(fields);
    let payload = match serde_json::to_vec(&body) {
        Ok(p) => p,
        Err(e) => return err_reply(&format!("failed to serialize {command}: {e}")),
    };
    match ctx
        .dev
        .send_command(SPP_JSON_COMMAND_ID, &payload, true)
        .await
    {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("{command} failed: {e}")),
    }
}

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let args = ctx.args;
    let kw = ctx.kwargs;
    let get_i64 = |name: &str, idx: usize, default: i64| -> i64 {
        kw.and_then(|v| v.get(name))
            .and_then(|v| v.as_i64())
            .or_else(|| args.get(idx).copied())
            .unwrap_or(default)
    };

    match method {
        "aid_sleep.play" => {
            let sleep_id = get_i64("SleepId", 0, 0);
            let sleep_type = get_i64("Type", 1, 0);
            let mut fields = serde_json::Map::new();
            fields.insert("SleepId".to_string(), json!(sleep_id));
            fields.insert("Type".to_string(), json!(sleep_type));
            send_json_command(&ctx, "AidSleep/Play", fields).await
        }
        "aid_sleep.exit" => send_json_command(&ctx, "AidSleep/Exit", serde_json::Map::new()).await,
        "aid_sleep.delete" => {
            let sleep_id = get_i64("SleepId", 0, 0);
            let sleep_type = get_i64("Type", 1, 0);
            let mut fields = serde_json::Map::new();
            fields.insert("SleepId".to_string(), json!(sleep_id));
            fields.insert("Type".to_string(), json!(sleep_type));
            send_json_command(&ctx, "AidSleep/Delete", fields).await
        }
        _ => err_reply(&format!("unknown aid_sleep method: {method}")),
    }
}
