use super::CallCtx;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};
use std::time::Duration;

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    match method {
        "game.show_game" | "show_game" => show_game(ctx).await,
        "game.hide_game" | "hide_game" | "game.exit_game" | "exit_game" => hide_game(ctx).await,
        "game.set_key_down" | "set_key_down" => set_key_down(ctx).await,
        "game.set_key_up" | "set_key_up" => set_key_up(ctx).await,
        "game.set_magic_ball_answer" | "set_magic_ball_answer" => set_magic_ball_answer(ctx).await,
        "game.send_gamecontrol" | "send_gamecontrol" => send_gamecontrol(ctx).await,
        _ => err_reply("unimplemented game command"),
    }
}
async fn show_game(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let value = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("value"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
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

async fn hide_game(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;

    match dev.send_command(0xa0, &[0x00, 0x00], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("hide_game/exit_game failed: {e}")),
    }
}

async fn set_key_down(ctx: CallCtx<'_>) -> Value {
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
    match dev.send_command(0x17, &[key], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_key_down failed: {e}")),
    }
}

async fn set_key_up(ctx: CallCtx<'_>) -> Value {
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
    match dev.send_command(0x21, &[key], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_key_up failed: {e}")),
    }
}

async fn set_magic_ball_answer(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let answer = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("answer"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    match dev.send_command(0x88, &[answer], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_magic_ball_answer failed: {e}")),
    }
}

async fn send_gamecontrol(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    let value_arg = raw_args.first().or_else(|| kw.and_then(|v| v.get("value")));

    let control_value = match value_arg {
        Some(Value::String(s)) => match s.to_lowercase().as_str() {
            "left" => 1,
            "right" => 2,
            "up" => 3,
            "down" => 4,
            "ok" => 5,
            _ => 0,
        },
        Some(Value::Number(n)) => n.as_i64().unwrap_or(0).byte(),
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
