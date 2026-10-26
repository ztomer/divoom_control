//! Text, live jobs and the built-in tools as MCP tools (P4.5).
//!
//! The daemon had all of these -- `render_widget` text, `live_job_start` /
//! `stop` / `list`, `scoreboard.set_scoreboard`, `timer.set_timer`,
//! `countdown.set_countdown` -- and none was a tool, so an agent had to speak
//! the raw socket for them. They join the one catalog (`mcp_tools::catalog`
//! appends [`catalog`]) and take their ranges from `crate::arg_bounds`, the
//! same statements the daemon handlers check.
//!
//! A separate file only because `mcp_tools.rs` would cross the 500-line cap;
//! it is the same registry, dispatched from the same `call_tool`.

use base64::Engine;
use serde_json::{json, Value};

use crate::arg_bounds::{
    BLUE_SCORE, COUNTDOWN_MINUTES, COUNTDOWN_SECONDS, IMAGE_SIZE, LEASE_TTL_MS, NOTIFY_DURATION_MS,
    RED_SCORE,
};
use crate::daemon_target::DaemonTarget;
use crate::error_code::ToolError;
use crate::mcp_daemon::{cmd, cmd_ok, dc};

/// `set_timer` actions and the 0x72 control flag each sends.
pub const TIMER_ACTIONS: [(&str, i64); 3] = [("stop", 0), ("start", 1), ("reset", 2)];
/// `set_countdown` actions and their control flags.
pub const COUNTDOWN_ACTIONS: [(&str, i64); 2] = [("start", 0), ("stop", 1)];

fn names<T>(table: &[(&'static str, T)]) -> Vec<&'static str> {
    table.iter().map(|(n, _)| *n).collect()
}

fn action(a: &Value, table: &[(&'static str, i64)], default: &str) -> Result<i64, String> {
    let name = a.get("action").and_then(Value::as_str).unwrap_or(default);
    table
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, f)| *f)
        .ok_or_else(|| format!("action must be one of {:?} (got {name:?})", names(table)))
}

/// The tools this file adds, in catalog form.
pub fn catalog() -> Vec<Value> {
    use crate::mcp_catalog::{tool, Effect};
    let kinds = crate::live_jobs::JOB_KINDS.to_vec();
    vec![
        tool("show_text", Effect::Write, &[("ok","boolean"),("text","string"),("size","integer")], "Draw text on the panel at its own resolution, in the device font (the frame render_widget's text kind previews). color is #RRGGBB, white by default.",
            &json!({"type":"object","properties":{"text":{"type":"string"},"color":{"type":"string"},"size":IMAGE_SIZE.schema()},"required":["text"]})),
        tool("live_job_start", Effect::Write, &[("ok","boolean"),("mac","string"),("kind","string"),("params","object")], "Start a live widget on the panel -- sysmon, stocks (params.symbol), weather (params.location), music (macOS) -- replacing the one it runs. Frames are rendered at the panel's size unless params.size says otherwise.",
            &json!({"type":"object","properties":{"kind":{"type":"string","enum":kinds},"params":{"type":"object"}},"required":["kind"]})),
        tool("live_job_stop", Effect::Write, &[("ok","boolean"),("mac","string"),("kind","string"),("stopped","any")], "Stop the panel's live widget of this kind.",
            &json!({"type":"object","properties":{"kind":{"type":"string","enum":kinds}},"required":["kind"]})),
        tool("live_job_list", Effect::Read, &[], "List the live widgets running, on one panel (mac) or all of them.",
            &json!({"type":"object","properties":{}})),
        tool("set_scoreboard", Effect::Write, &[("ok","boolean"),("red_score","integer"),("blue_score","integer"),("on","boolean")], "Show the scoreboard with these scores (0-999 each); on=false hides it.",
            &json!({"type":"object","properties":{"red_score":RED_SCORE.schema(),"blue_score":BLUE_SCORE.schema(),"on":{"type":"boolean"}},"required":["red_score","blue_score"]})),
        tool("set_timer", Effect::Write, &[("ok","boolean"),("action","any")], "Control the stopwatch: start, stop (pause) or reset.",
            &json!({"type":"object","properties":{"action":{"type":"string","enum":names(&TIMER_ACTIONS)}},"required":["action"]})),
        tool("set_countdown", Effect::Write, &[("ok","boolean"),("action","any"),("minutes","integer"),("seconds","integer")], "Start a countdown of minutes:seconds, or stop the running one.",
            &json!({"type":"object","properties":{"action":{"type":"string","enum":names(&COUNTDOWN_ACTIONS)},"minutes":COUNTDOWN_MINUTES.schema(),"seconds":COUNTDOWN_SECONDS.schema()},"required":["action"]})),
        tool("notify", Effect::Write, &[("ok","boolean"),("text","string"),("size","integer"),("duration_ms","integer"),("mac","any"),("lease","string")], "Show a short message on the panel for duration_ms, then give the panel back -- its live widget returns by itself; nothing waits. Refused while someone holds the panel's lease. Returns the notification's lease: lease_release dismisses it early.",
            &json!({"type":"object","properties":{"text":{"type":"string"},"duration_ms":NOTIFY_DURATION_MS.schema(),"color":{"type":"string"},"size":IMAGE_SIZE.schema()},"required":["text","duration_ms"]})),
        tool("lease_acquire", Effect::Write, &[("ok","boolean")], "Borrow the panel's screen for ttl_ms (renew before it runs out). Pass the returned lease to every drawing call; anyone else is refused, and the panel's live widget pauses. When the lease ends -- released, or expired because you stopped renewing -- the widget's newest frame comes back at once.",
            &json!({"type":"object","properties":{"ttl_ms":LEASE_TTL_MS.schema(),"holder":{"type":"string","description":"Who is asking, shown to anyone refused."}},"required":["ttl_ms"]})),
        tool("lease_renew", Effect::Write, &[("ok","boolean")], "Extend your lease to ttl_ms from now.",
            &json!({"type":"object","properties":{"lease":{"type":"string"},"ttl_ms":LEASE_TTL_MS.schema()},"required":["lease","ttl_ms"]})),
        tool("lease_release", Effect::Write, &[("ok","boolean")], "Give the screen back now; says what the panel went back to (job: its live widget, none: nothing to restore).",
            &json!({"type":"object","properties":{"lease":{"type":"string"}},"required":["lease"]})),
    ]
}

/// Dispatch one of this file's tools; `None` for a name it does not own.
pub async fn call(
    name: &str,
    a: &Value,
    target: &DaemonTarget,
) -> Option<Result<Value, ToolError>> {
    let mac = a.get("mac").and_then(Value::as_str);
    Some(match name {
        "show_text" => show_text(a, target, mac).await,
        "live_job_start" => live_job_start(a, target, mac).await,
        "live_job_stop" => live_job_stop(a, target, mac).await,
        "live_job_list" => {
            let args = mac.map_or_else(|| json!({}), |m| json!({ "mac": m }));
            cmd_ok(target, "live_job_list", args).await
        }
        "set_scoreboard" => set_scoreboard(a, target, mac).await,
        "set_timer" => {
            async {
                let flag = action(a, &TIMER_ACTIONS, "start")?;
                dc(target, "timer.set_timer", json!([flag]), mac).await?;
                Ok(json!({ "ok": true, "action": a["action"] }))
            }
            .await
        }
        "set_countdown" => set_countdown(a, target, mac).await,
        "notify" => notify(a, target, mac).await,
        "lease_acquire" | "lease_renew" | "lease_release" => lease(name, a, target, mac).await,
        _ => return None,
    })
}

fn text_arg(a: &Value) -> Result<&str, String> {
    a.get("text")
        .and_then(Value::as_str)
        .filter(|t| !t.trim().is_empty())
        .ok_or_else(|| "text must be a non-empty string".into())
}

async fn show_text(
    a: &Value,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    let text = text_arg(a)?;
    let size = crate::mcp_tools::panel_size(a, target, mac).await?;
    draw_text(a, text, size, target, mac).await?;
    Ok(json!({ "ok": true, "text": text, "size": size }))
}

/// Render `text` in the device font and push it as one frame at `size`.
async fn draw_text(
    a: &Value,
    text: &str,
    size: u32,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<(), ToolError> {
    // The text renderer draws up to 64 px; a larger panel gets that frame
    // scaled by a whole factor (128 = 2x), which nearest-neighbour keeps
    // exact, rather than a 64 px frame on a 128 px panel.
    let drawn = size.min(64);
    let mut params = json!({ "text": text, "font_size": if drawn > 16 { 2 } else { 1 } });
    if let Some(c) = a.get("color").and_then(Value::as_str) {
        params["color"] = json!(c);
    }
    let reply = cmd_ok(
        target,
        "render_widget",
        json!({ "kind": "text", "size": drawn, "params": params }),
    )
    .await?;
    let rgb = reply
        .get("frame_rgb_b64")
        .and_then(Value::as_str)
        .ok_or("render_widget returned no frame")
        .and_then(|b| {
            base64::engine::general_purpose::STANDARD
                .decode(b)
                .map_err(|_| "render_widget returned a bad frame")
        })?;
    let img = image::RgbImage::from_raw(drawn, drawn, rgb)
        .ok_or("render_widget frame has the wrong size")?;
    let frame = crate::image_fit::fit_frame(
        &image::DynamicImage::ImageRgb8(img),
        size,
        crate::image_fit::Fit::Exact,
    )?;
    let edge = i32::try_from(size).map_err(|e| e.to_string())?;
    crate::mcp_tools::push_frames(target, &[(frame.into_raw(), edge, edge, 100)], mac).await
}

/// `notify` (P4.7): a screen lease whose TTL IS the notification's
/// duration, with the text drawn under it. Nothing waits for the end: the
/// lease lapses by itself and the daemon hands the panel back (its live
/// widget's newest frame; see `crate::lease`), so the tool returns at once
/// and an agent that dies mid-notification cannot leave it up. A failed
/// draw gives the lease back at once rather than holding a blank borrow.
async fn notify(a: &Value, target: &DaemonTarget, mac: Option<&str>) -> Result<Value, ToolError> {
    let text = text_arg(a)?;
    let duration = NOTIFY_DURATION_MS.read(a)?;
    let size = crate::mcp_tools::panel_size(a, target, mac).await?;
    let mut args = json!({ "ttl_ms": duration, "holder": "notification" });
    if let Some(m) = mac {
        args["mac"] = json!(m);
    }
    let lease = cmd_ok(target, "lease_acquire", args).await?;
    let token = lease
        .get("token")
        .and_then(Value::as_str)
        .ok_or("lease_acquire returned no token")?
        .to_string();
    // The panel the lease landed on, so the draw cannot go anywhere else.
    let panel = lease.get("mac").and_then(Value::as_str).or(mac);
    let drawn =
        crate::mcp_daemon::with_lease(Some(token.clone()), draw_text(a, text, size, target, panel))
            .await;
    if let Err(e) = drawn {
        let _ = cmd(target, "lease_release", json!({ "token": token })).await;
        return Err(e);
    }
    Ok(json!({
        "ok": true, "text": text, "size": size, "duration_ms": duration,
        "mac": panel, "lease": token,
    }))
}

/// The panel a live-job call is about: the one named, else the active one.
async fn job_panel(target: &DaemonTarget, mac: Option<&str>) -> Result<(String, Value), ToolError> {
    let args = mac.map_or_else(|| json!({}), |m| json!({ "mac": m }));
    let status = cmd(target, "device_status", args).await?;
    let id = mac
        .map(str::to_string)
        .or_else(|| {
            status
                .get("mac")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .ok_or("no panel named and none active: pass mac")?;
    Ok((id, status))
}

async fn live_job_start(
    a: &Value,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    let kind = a
        .get("kind")
        .and_then(Value::as_str)
        .ok_or("kind must be a string")?;
    if !crate::live_jobs::JOB_KINDS.contains(&kind) {
        return Err(format!(
            "kind must be one of {:?} (got {kind:?})",
            crate::live_jobs::JOB_KINDS
        )
        .into());
    }
    let (id, status) = job_panel(target, mac).await?;
    let mut params = a.get("params").cloned().unwrap_or_else(|| json!({}));
    if !params.is_object() {
        return Err("params must be an object".into());
    }
    // Every job renders at params.size, default 16: an agent's job on a 64x64
    // panel would draw a quarter of it. The panel's own size, unless told.
    if params.get("size").is_none() {
        if let Some(w) = status.get("width").and_then(Value::as_u64) {
            params["size"] = json!(w);
        }
    }
    cmd_ok(
        target,
        "live_job_start",
        json!({ "mac": id, "kind": kind, "params": params }),
    )
    .await?;
    Ok(json!({ "ok": true, "mac": id, "kind": kind, "params": params }))
}

async fn live_job_stop(
    a: &Value,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    let kind = a
        .get("kind")
        .and_then(Value::as_str)
        .ok_or("kind must be a string")?;
    let (id, _) = job_panel(target, mac).await?;
    let reply = cmd_ok(target, "live_job_stop", json!({ "mac": id, "kind": kind })).await?;
    Ok(
        json!({ "ok": true, "mac": id, "kind": kind, "stopped": reply.get("stopped").cloned().unwrap_or(Value::Null) }),
    )
}

async fn set_scoreboard(
    a: &Value,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    let red = RED_SCORE.read(a)?;
    let blue = BLUE_SCORE.read(a)?;
    let on = a.get("on").and_then(Value::as_bool).unwrap_or(true);
    dc(
        target,
        "scoreboard.set_scoreboard",
        json!([i64::from(on), red, blue]),
        mac,
    )
    .await?;
    Ok(json!({ "ok": true, "red_score": red, "blue_score": blue, "on": on }))
}

/// The three lease tools: the daemon's commands, with `lease` for `token`.
async fn lease(
    name: &str,
    a: &Value,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    let mut args = json!({});
    if name == "lease_acquire" {
        args["ttl_ms"] = json!(LEASE_TTL_MS.read(a)?);
        args["holder"] = json!(a
            .get("holder")
            .and_then(Value::as_str)
            .unwrap_or("MCP agent"));
        if let Some(m) = mac {
            args["mac"] = json!(m);
        }
    } else {
        let token = a
            .get("lease")
            .and_then(Value::as_str)
            .ok_or("lease must be the token lease_acquire returned")?;
        args["token"] = json!(token);
        if name == "lease_renew" {
            args["ttl_ms"] = json!(LEASE_TTL_MS.read(a)?);
        }
    }
    let mut reply = cmd_ok(target, name, args).await?;
    let obj = reply
        .as_object_mut()
        .ok_or("the daemon's reply is not an object")?;
    obj.remove("success");
    if let Some(t) = obj.remove("token") {
        obj.insert("lease".into(), t);
    }
    obj.insert("ok".into(), json!(true));
    Ok(reply)
}

async fn set_countdown(
    a: &Value,
    target: &DaemonTarget,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    let flag = action(a, &COUNTDOWN_ACTIONS, "start")?;
    let minutes = COUNTDOWN_MINUTES.read_or(a, 0)?;
    let seconds = COUNTDOWN_SECONDS.read_or(a, 0)?;
    dc(
        target,
        "countdown.set_countdown",
        json!([flag, minutes, seconds]),
        mac,
    )
    .await?;
    Ok(json!({ "ok": true, "action": a["action"], "minutes": minutes, "seconds": seconds }))
}

#[cfg(test)]
#[path = "mcp_more_tools_tests.rs"]
mod tests;
