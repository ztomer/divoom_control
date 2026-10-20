use super::link_gone;
use super::CallCtx;
use crate::arg_bounds::{BLUE_SCORE, COUNTDOWN_MINUTES, COUNTDOWN_SECONDS, RED_SCORE};
use crate::protocol::{
    err_code,
    ErrorCode::{BadRequest, UnknownCommand, Unsupported},
};
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

use super::read::read_reply;

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    match method {
        "scoreboard.set_scoreboard" | "set_scoreboard" => set_scoreboard(ctx).await,
        "scoreboard.get_scoreboard" | "get_scoreboard" => get_scoreboard(ctx).await,
        "timer.set_timer" | "set_timer" => set_timer(ctx).await,
        "timer.get_timer" | "get_timer" => get_timer(ctx).await,
        "countdown.set_countdown" | "set_countdown" => set_countdown(ctx).await,
        "countdown.get_countdown" | "get_countdown" => get_countdown(ctx).await,
        "noise.set_noise" | "set_noise" => set_noise(ctx).await,
        "noise.get_noise" | "get_noise" => get_noise(ctx).await,
        "device.show_notification" | "show_notification" | "notification.show_notification" => {
            show_notification(ctx).await
        }
        "device.show_notification_text"
        | "show_notification_text"
        | "notification.show_notification_text" => show_notification_text(ctx).await,
        // Generic tool read-back (Python Tool.get_tool_info): 0x71 [tool_type] →
        // parse per type (GTI offsets). Types: 0=timer 1=score 2=noise 3=countdown.
        "tool.get_tool_info" | "get_tool_info" => get_tool_info(ctx).await,
        // Generic tool setter (Python Tool.set_tool_info): 0x72 [game_mode_index,
        // *per-type args]. 0=timer[ctrl_flag] 1=score[on_off, red LE16, blue LE16]
        // 2=noise[ctrl_flag] 3=countdown[ctrl_flag, minutes, seconds].
        "tool.set_tool_info" | "set_tool_info" => set_tool_info(ctx).await,
        _ => err_code(UnknownCommand, "unimplemented tools command"),
    }
}
async fn set_scoreboard(ctx: CallCtx<'_>) -> Value {
    let payload = match scoreboard_payload(ctx.args, ctx.kwargs) {
        Ok(p) => p,
        Err(e) => return err_code(BadRequest, &e),
    };
    match ctx.dev.send_command(0x72, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("set_scoreboard", &e),
    }
}

/// The 0x72 scoreboard payload for `set_scoreboard(on_off, red_score,
/// blue_score)`, positional or by keyword -- one panel's and the wall's
/// (P6.5), so the two cannot disagree on the layout.
///
/// # Errors
///
/// A score outside the shared bounds (`crate::arg_bounds`), refused rather
/// than clamped: 1500 used to become 999 without a word.
pub(crate) fn scoreboard_payload(
    args: &[i64],
    kw: Option<&serde_json::Map<String, Value>>,
) -> Result<Vec<u8>, String> {
    let pick = |idx: usize, name: &str| {
        args.get(idx)
            .copied()
            .or_else(|| kw.and_then(|v| v.get(name)).and_then(Value::as_i64))
            .unwrap_or(0)
    };
    let on_off = pick(0, "on_off").byte();
    let (red_score, blue_score) = match (
        RED_SCORE.check(pick(1, "red_score")),
        BLUE_SCORE.check(pick(2, "blue_score")),
    ) {
        (Ok(r), Ok(b)) => (r.word(), b.word()),
        (Err(e), _) | (_, Err(e)) => return Err(format!("set_scoreboard: {e}")),
    };
    let mut payload = Vec::with_capacity(6);
    payload.push(1u8); // TOOL_TYPE_SCORE
    payload.push(on_off);
    payload.extend_from_slice(&red_score.to_le_bytes());
    payload.extend_from_slice(&blue_score.to_le_bytes());
    Ok(payload)
}

async fn get_scoreboard(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;

    read_reply(dev, "get_scoreboard", 0x71, &[1], ctx.timeout, 5, |p| {
        json!({
            "success": true,
            "result": {
                "on_off": i64::from(p[0]),
                "red_score": i64::from(u16::from_le_bytes([p[1], p[2]])),
                "blue_score": i64::from(u16::from_le_bytes([p[3], p[4]])),
            }
        })
    })
    .await
}

async fn set_timer(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let ctrl_flag = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("ctrl_flag"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let payload = [0u8, ctrl_flag]; // TOOL_TYPE_TIMER = 0
    match dev.send_command(0x72, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("set_timer", &e),
    }
}

async fn get_timer(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;

    read_reply(dev, "get_timer", 0x71, &[0], ctx.timeout, 1, |p| {
        json!({
            "success": true,
            "result": {
                "status": i64::from(p[0]),
            }
        })
    })
    .await
}

async fn set_countdown(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let ctrl_flag = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("ctrl_flag"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let minutes = args
        .get(1)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("minutes"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0);
    let seconds = args
        .get(2)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("seconds"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0);
    // Refused, not narrowed: `.byte()` sent 300 minutes as 44.
    let (minutes, seconds) = match (
        COUNTDOWN_MINUTES.check(minutes),
        COUNTDOWN_SECONDS.check(seconds),
    ) {
        (Ok(m), Ok(s)) => (m.byte(), s.byte()),
        (Err(e), _) | (_, Err(e)) => return err_code(BadRequest, &format!("set_countdown: {e}")),
    };
    let payload = [3u8, ctrl_flag, minutes, seconds]; // TOOL_TYPE_COUNTDOWN = 3
    match dev.send_command(0x72, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("set_countdown", &e),
    }
}

async fn get_countdown(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;

    read_reply(dev, "get_countdown", 0x71, &[3], ctx.timeout, 3, |p| {
        json!({
            "success": true,
            "result": {
                "status": i64::from(p[0]),
                "minutes": i64::from(p[1]),
                "seconds": i64::from(p[2]),
            }
        })
    })
    .await
}

async fn set_noise(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let ctrl_flag = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("ctrl_flag"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let payload = [2u8, ctrl_flag]; // TOOL_TYPE_NOISE = 2
    match dev.send_command(0x72, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("set_noise", &e),
    }
}

async fn get_noise(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;

    read_reply(dev, "get_noise", 0x71, &[2], ctx.timeout, 1, |p| {
        json!({
            "success": true,
            "result": {
                "status": i64::from(p[0]),
            }
        })
    })
    .await
}

async fn show_notification(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let app_type = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("app_type"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(1)
        .byte();
    let Some(wire) = crate::ancs::bare(app_type) else {
        return err_code(
            BadRequest,
            &format!("show_notification: app_type {app_type} has no wire value"),
        );
    };
    match dev.send_command(0x50, &[wire], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("show_notification", &e),
    }
}

async fn show_notification_text(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    let app_type = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("app_type"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(1)
        .byte();
    let text = raw_args
        .get(1)
        .and_then(|v| v.as_str())
        .or_else(|| kw.and_then(|v| v.get("text")).and_then(|v| v.as_str()))
        .unwrap_or("");
    let payload = crate::ancs::with_text(app_type, text);
    match dev.send_command(0x50, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("show_notification_text", &e),
    }
}

async fn get_tool_info(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let tool_type = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("tool_type"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0);
    // The answer's shape depends on the tool: the scoreboard carries two
    // scores, the timer and the noise one byte, the countdown three, and
    // 255 ("not in game mode") carries nothing to read. A tool type this
    // daemon cannot decode is refused, not answered with a null (P2.8).
    let min_len = match tool_type {
        1 => 5,
        0 | 2 => 1,
        3 => 3,
        255 => 0,
        other => {
            return err_code(
                Unsupported,
                &format!("get_tool_info: this daemon cannot read tool type {other}"),
            )
        }
    };
    read_reply(
        dev,
        "get_tool_info",
        0x71,
        &[tool_type.byte()],
        ctx.timeout,
        min_len,
        |r| {
            let result = match tool_type {
                1 => json!({
                    "on_off": i64::from(r[0]),
                    "red_score": i64::from(u16::from_le_bytes([r[1], r[2]])),
                    "blue_score": i64::from(u16::from_le_bytes([r[3], r[4]])),
                }),
                0 | 2 => json!({"status": i64::from(r[0])}),
                3 => json!({
                    "status": i64::from(r[0]), "minutes": i64::from(r[1]), "seconds": i64::from(r[2]),
                }),
                _ => json!({"status": "not in game mode"}),
            };
            json!({"success": true, "result": result})
        },
    )
    .await
}

async fn set_tool_info(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let gmi = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("game_mode_index"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0);
    let g = |n: &str| {
        kw.and_then(|v| v.get(n))
            .and_then(serde_json::Value::as_i64)
    };
    let mut payload = vec![gmi.byte()];
    match gmi {
        0 | 2 => match g("ctrl_flag") {
            Some(c) => payload.push(c.byte()),
            None => return err_code(BadRequest, "set_tool_info: timer/noise need 'ctrl_flag'"),
        },
        1 => match g("on_off") {
            Some(on_off) => {
                payload.push(on_off.byte());
                payload.extend_from_slice(&(g("red_score").unwrap_or(0).word()).to_le_bytes());
                payload.extend_from_slice(&(g("blue_score").unwrap_or(0).word()).to_le_bytes());
            }
            None => return crate::command_args::missing("set_tool_info score", "'on_off'"),
        },
        3 => match (g("ctrl_flag"), g("minutes"), g("seconds")) {
            (Some(c), Some(m), Some(s)) => {
                payload.push(c.byte());
                payload.push(m.byte());
                payload.push(s.byte());
            }
            _ => {
                return err_code(
                    BadRequest,
                    "set_tool_info: countdown needs ctrl_flag/minutes/seconds",
                )
            }
        },
        _ => {
            return err_code(
                BadRequest,
                &format!("set_tool_info: unknown game_mode_index {gmi}"),
            )
        }
    }
    match dev.send_command(0x72, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => link_gone("set_tool_info", &e),
    }
}
