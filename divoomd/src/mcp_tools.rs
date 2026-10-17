//! MCP tool catalog + dispatch.
//!
//! Ported from `divoom_lib/mcp_tools.py`. Each tool forwards to the daemon as a
//! `device_call` (or top-level command) over the local unix socket or a remote
//! TCP connection (`crate::daemon_target`); file-based tools decode locally (the
//! `image` crate) and push rgb.

use base64::Engine;
use serde_json::{json, Value};

use crate::daemon_target::DaemonTarget;
use crate::image_fit::Fit;

// name -> channel int (LIGHT_MODE_NAMES in mcp_tools.py).
const LIGHT_MODES: [(&str, i64); 8] = [
    ("clock", 0),
    ("lightning", 1),
    ("cloud", 2),
    ("vj", 3),
    ("visualizer", 4),
    ("design", 5),
    ("scoreboard", 6),
    ("animation", 7),
];
// name -> WeatherType int (weather.py: 1=clear,3=cloudy,5=storm,6=rain,8=snow,9=fog).
const WEATHER_TYPES: [(&str, i64); 6] = [
    ("clear", 1),
    ("cloudy", 3),
    ("thunderstorm", 5),
    ("rain", 6),
    ("snow", 8),
    ("fog", 9),
];

/// The `tools/list` descriptors (name + description + inputSchema), matching the
/// Python `_SCHEMAS`/`_DESCRIPTIONS`.
#[must_use]
pub fn catalog() -> Value {
    let int = |lo: i64, hi: i64| json!({ "type": "integer", "minimum": lo, "maximum": hi });
    let resize = json!({
        "type": "string",
        "enum": Fit::ALL.iter().map(|(n, _)| *n).collect::<Vec<_>>(),
        "default": "fit",
    });
    json!([
        tool("set_volume", "Set the device's speaker volume (0-15).",
            &json!({"type":"object","properties":{"level":int(0,15)},"required":["level"]})),
        tool("set_brightness", "Set the device's display brightness (0-100).",
            &json!({"type":"object","properties":{"level":int(0,100)},"required":["level"]})),
        tool("set_light_mode", "Switch the active channel (clock, lightning, cloud, vj, visualizer, design, scoreboard, animation).",
            &json!({"type":"object","properties":{"mode":{"type":"string","enum":LIGHT_MODES.iter().map(|(n,_)|*n).collect::<Vec<_>>()}},"required":["mode"]})),
        tool("set_weather", "Push a temperature + weather icon to the device's built-in weather widget.",
            &json!({"type":"object","properties":{"temperature_c":int(-127,128),"weather":{"type":"string","enum":WEATHER_TYPES.iter().map(|(n,_)|*n).collect::<Vec<_>>()}},"required":["temperature_c","weather"]})),
        tool("set_alarm", "Set or disable one of the device's 10 alarms.",
            &json!({"type":"object","properties":{"index":int(0,9),"hour":int(0,23),"minute":int(0,59),"weekday_mask":int(0,127),"enabled":{"type":"boolean"}},"required":["index","hour","minute"]})),
        tool("set_radio", "Tune the FM radio (freq_x10 = MHz x 10, e.g. 875 = 87.5).",
            &json!({"type":"object","properties":{"freq_x10":int(875,1080)},"required":["freq_x10"]})),
        tool("set_low_power", "Enable or disable the device's low-power mode.",
            &json!({"type":"object","properties":{"enabled":{"type":"boolean"}},"required":["enabled"]})),
        tool("set_screen_orientation", "Rotate the device's display 0/90/180/270 degrees; optionally mirror/flip.",
            &json!({"type":"object","properties":{"degrees":{"type":"integer","enum":[0,90,180,270]},"mirror":{"type":"boolean"}},"required":["degrees"]})),
        tool("show_image", "Draw a local image file on the panel at the panel's own resolution (from its model; pass size when it has none). resize: fit (whole image, padded black), fill (cover, cropped), exact (stretched), none (must already be the panel's size, else an error). Colours are reduced to the panel's 256-colour palette only when the image has more.",
            &json!({"type":"object","properties":{"file":{"type":"string","description":"Local filesystem path to the image."},"resize":resize,"size":int(8,128)},"required":["file"]})),
        tool("push_animation", "Play a GIF/animation on the panel: every frame, each for its own duration (GIF delays; 50 ms minimum), at the panel's resolution under the same resize policy as show_image. Provide 'file' (path) or 'data' (base64).",
            &json!({"type":"object","properties":{"file":{"type":"string"},"data":{"type":"string"},"resize":resize,"size":int(8,128)},"oneOf":[{"required":["file"]},{"required":["data"]}]})),
        tool("play_sound", "Beep the device (best-effort; some firmware no-ops).",
            &json!({"type":"object","properties":{"duration_ms":int(100,3000)},"required":["duration_ms"]})),
        tool("get_capabilities", "Describe a panel: link state, model, width/height in pixels (how it was decided: model_source), and the features the vendor app enables for that model (speaker, sd_card, temp_sensor, wifi, clock_style; null for an unrecognised model). There is no FM-radio flag: the vendor app does not decide FM per model.",
            &json!({"type":"object","properties":{},"additionalProperties":false})),
        tool("get_device_state", "Read the device's current volume, brightness, channel, orientation, mirror.",
            &json!({"type":"object","properties":{},"additionalProperties":false})),
        tool("list_screens", "List every screen the daemon knows or the saved layout places (`screens`): each with mac, connected (live link), selected, model, width/height (null when never seen), features, and its saved x/y/room; plus wall state and slots.",
            &json!({"type":"object","properties":{},"additionalProperties":false})),
    ])
}

fn tool(name: &str, desc: &str, schema: &Value) -> Value {
    let mut s = schema.clone();
    if let Some(props) = s.get_mut("properties").and_then(Value::as_object_mut) {
        if name != "list_screens" {
            props.insert(
                "mac".into(),
                json!({
                    "type": "string",
                    "description": "Optional MAC address of the target display (default: active display)."
                }),
            );
        }
    }
    json!({ "name": name, "description": desc, "inputSchema": s })
}

/// Dispatch a tools/call. Returns the tool's result dict, or Err(message) for a
/// validation / device error (the caller marks it isError).
///
/// # Errors
///
/// When a required argument is missing or has the wrong type -- each message
/// names the argument -- and from the daemon call the tool delegates to.
///
/// # Panics
///
/// If a mutex guarding shared tool state is poisoned.
pub async fn call_tool(name: &str, a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    match name {
        "set_volume" => {
            let level = need_int(a, "level", 0, 15)?;
            crate::mcp_daemon::dc(target, "music.set_volume", json!([level]), mac).await?;
            Ok(json!({ "ok": true, "level": level }))
        }
        "set_brightness" => {
            let level = need_int(a, "level", 0, 100)?;
            crate::mcp_daemon::dc(target, "device.set_brightness", json!([level]), mac).await?;
            Ok(json!({ "ok": true, "level": level }))
        }
        "set_light_mode" => set_light_mode(a, target).await,
        "set_weather" => set_weather(a, target).await,
        "set_alarm" => set_alarm(a, target).await,
        "set_radio" => {
            let freq = need_int(a, "freq_x10", 875, 1080)?;
            crate::mcp_daemon::dc(target, "radio.set_radio_frequency", json!([freq]), mac).await?;
            Ok(json!({ "ok": true, "freq_x10": freq }))
        }
        "set_low_power" => set_low_power(a, target).await,
        "set_screen_orientation" => set_screen_orientation(a, target).await,
        "show_image" => show_image(a, target).await,
        "push_animation" => push_animation(a, target).await,
        "play_sound" => {
            let dur = need_int(a, "duration_ms", 100, 3000)?;
            crate::mcp_daemon::dc(target, "control.set_hot", json!([1]), mac).await?;
            Ok(json!({ "ok": true, "duration_ms": dur }))
        }
        "get_capabilities" => {
            let args = a
                .get("mac")
                .map_or_else(|| json!({}), |m| json!({ "mac": m }));
            crate::mcp_daemon::cmd(target, "device_status", args).await
        }
        "get_device_state" => get_device_state(a, target).await,
        "list_screens" => crate::mcp_daemon::cmd(target, "get_topology", json!({})).await,
        other => Err(format!("unknown tool: {other}")),
    }
}
async fn set_light_mode(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let mode = a
        .get("mode")
        .and_then(|v| v.as_str())
        .ok_or("mode must be a string")?;
    let channel = LIGHT_MODES
        .iter()
        .find(|(n, _)| *n == mode)
        .map(|(_, c)| *c)
        .ok_or_else(|| {
            format!(
                "mode must be one of {:?}",
                LIGHT_MODES.iter().map(|(n, _)| *n).collect::<Vec<_>>()
            )
        })?;
    crate::mcp_daemon::dc(target, "control.set_light_mode", json!([channel]), mac).await?;
    Ok(json!({ "ok": true, "mode": mode, "channel": channel }))
}

/// The wire value for a weather icon name.
///
/// `pub(crate)` because the `set-temperature` CLI verb validates the name with
/// it, before a panel is resolved. One table, one place that can be wrong.
pub(crate) fn weather_id(name: &str) -> Result<i64, String> {
    WEATHER_TYPES
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, t)| *t)
        .ok_or_else(|| {
            format!(
                "weather must be one of {:?}",
                WEATHER_TYPES.iter().map(|(n, _)| *n).collect::<Vec<_>>()
            )
        })
}

async fn set_weather(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let temp = need_int(a, "temperature_c", -127, 128)?;
    let weather = a
        .get("weather")
        .and_then(|v| v.as_str())
        .ok_or("weather must be a string")?;
    let wt = weather_id(weather)?;
    crate::mcp_daemon::dc(target, "weather.set", json!([temp, wt]), mac).await?;
    Ok(json!({ "ok": true, "temperature_c": temp, "weather": weather }))
}

async fn set_alarm(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let index = need_int(a, "index", 0, 9)?;
    let hour = need_int(a, "hour", 0, 23)?;
    let minute = need_int(a, "minute", 0, 59)?;
    let week = opt_int(a, "weekday_mask", 0, 127, 0)?;
    let enabled = a
        .get("enabled")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(true);
    let status = i32::from(enabled);
    // set_alarm(index, status, hour, minute, week, mode=0, trigger_mode=1)
    crate::mcp_daemon::dc(
        target,
        "alarm.set_alarm",
        json!([index, status, hour, minute, week, 0, 1]),
        mac,
    )
    .await?;
    Ok(
        json!({ "ok": true, "index": index, "hour": hour, "minute": minute, "weekday_mask": week, "enabled": enabled }),
    )
}

async fn set_low_power(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let enabled = a
        .get("enabled")
        .and_then(serde_json::Value::as_bool)
        .ok_or("enabled must be a boolean")?;
    crate::mcp_daemon::dc(
        target,
        "device.set_low_power_switch",
        json!([i32::from(enabled)]),
        mac,
    )
    .await?;
    Ok(json!({ "ok": true, "enabled": enabled }))
}

async fn set_screen_orientation(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let degrees = need_int(a, "degrees", 0, 270)?;
    let dir = match degrees {
        0 => 0,
        90 => 1,
        180 => 2,
        270 => 3,
        _ => return Err("degrees must be 0, 90, 180, or 270".into()),
    };
    let mirror = a
        .get("mirror")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false);
    crate::mcp_daemon::dc(target, "design.set_screen_dir", json!([dir]), mac).await?;
    crate::mcp_daemon::dc(target, "design.set_screen_mirror", json!([mirror]), mac).await?;
    Ok(json!({ "ok": true, "degrees": degrees, "mirror": mirror }))
}

async fn show_image(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);
    let (resize, policy) = resize_policy(a)?;
    let file = a
        .get("file")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("file must be a non-empty local path string")?;
    let bytes = std::fs::read(file).map_err(|e| format!("cannot read {file}: {e}"))?;
    let size = panel_size(a, target, mac).await?;
    let frames = decode(bytes, size, policy).await?;
    // An image tool shows an image: a GIF given here shows its first frame,
    // and `push_animation` is the tool that plays it.
    push_frames(target, &frames[..1.min(frames.len())], mac).await?;
    Ok(json!({ "ok": true, "file": file, "size": size, "resize": resize }))
}

async fn push_animation(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let file = a
        .get("file")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    let data = a
        .get("data")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    if file.is_some() == data.is_some() {
        return Err("provide exactly one of 'file' or 'data'".into());
    }
    let bytes = if let Some(f) = file {
        std::fs::read(f).map_err(|e| format!("cannot read {f}: {e}"))?
    } else {
        base64::engine::general_purpose::STANDARD
            .decode(data.unwrap())
            .map_err(|e| format!("invalid base64: {e}"))?
    };
    let (resize, policy) = resize_policy(a)?;
    let size = panel_size(a, target, mac).await?;
    let frames = decode(bytes, size, policy).await?;
    push_frames(target, &frames, mac).await?;
    Ok(json!({ "ok": true, "size": size, "resize": resize, "frames": frames.len() }))
}

async fn get_device_state(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let volume = crate::mcp_daemon::dc_result(target, "music.get_volume", json!([]), mac).await;
    let brightness =
        crate::mcp_daemon::dc_result(target, "device.get_brightness", json!([]), mac).await;
    let light_mode =
        crate::mcp_daemon::dc_result(target, "control.get_light_mode", json!([]), mac).await;
    let screen_dir =
        crate::mcp_daemon::dc_result(target, "design.get_screen_dir", json!([]), mac).await;
    let mirror =
        crate::mcp_daemon::dc_result(target, "design.get_screen_mirror", json!([]), mac).await;
    Ok(json!({
        "volume": volume, "brightness": brightness, "light_mode": light_mode,
        "screen_orientation": screen_dir, "mirror": mirror,
    }))
}

// --- helpers -----------------------------------------------------------------

/// Read a bounded integer out of a tool's arguments.
///
/// `pub(crate)` because the CLI verbs share these bounds rather than restating
/// them: a range that lives in two places is a range that gets changed in one.
/// The error text is phrased for a tool call, which is also how the CLI reports
/// it, so the bound reads the same on both surfaces.
pub(crate) fn need_int(a: &Value, key: &str, lo: i64, hi: i64) -> Result<i64, String> {
    let v = a
        .get(key)
        .and_then(serde_json::Value::as_i64)
        .ok_or_else(|| format!("{key} must be an integer"))?;
    if v < lo || v > hi {
        return Err(format!("{key} must be in [{lo}..{hi}] (got {v})"));
    }
    Ok(v)
}

fn opt_int(a: &Value, key: &str, lo: i64, hi: i64, default: i64) -> Result<i64, String> {
    match a.get(key) {
        None | Some(Value::Null) => Ok(default),
        Some(_) => need_int(a, key, lo, hi),
    }
}

/// The `resize` argument: its wire name and policy, `fit` when absent.
fn resize_policy(a: &Value) -> Result<(&str, Fit), String> {
    let name = a.get("resize").and_then(Value::as_str).unwrap_or("fit");
    Ok((name, Fit::parse(name)?))
}

/// The edge to draw at: `size` when the caller gives one, else the panel's
/// own width from `device_status` (P3.1). A panel with no model to go on (a
/// LAN panel advertises no name) has no known size, and guessing one is how
/// a 64x64 panel came to get 16x16 images -- so the caller is asked instead.
async fn panel_size(a: &Value, target: &DaemonTarget, mac: Option<&str>) -> Result<u32, String> {
    if a.get("size").is_some_and(|v| !v.is_null()) {
        let edge = need_int(a, "size", 8, 128)?;
        return u32::try_from(edge).map_err(|e| e.to_string());
    }
    let args = mac.map_or_else(|| json!({}), |m| json!({ "mac": m }));
    let status = crate::mcp_daemon::cmd(target, "device_status", args).await?;
    status
        .get("width")
        .and_then(Value::as_u64)
        .and_then(|w| u32::try_from(w).ok())
        .ok_or_else(|| {
            "the panel's size is unknown (it advertises no model name); pass size".to_string()
        })
}

/// Decode and fit every frame, off the async runtime (it is CPU-bound).
async fn decode(
    bytes: Vec<u8>,
    size: u32,
    policy: Fit,
) -> Result<Vec<crate::image_proc::Frame>, String> {
    tokio::task::spawn_blocking(move || {
        crate::image_proc::process_image_bytes_with(bytes, size, policy, 100)
    })
    .await
    .map_err(|e| format!("decode task: {e}"))?
}

/// Push fitted frames through the daemon's `show_image`, all in one call:
/// the daemon encodes each with its own duration and streams them as one
/// animation (P4.4). One frame is the same call with a list of one.
async fn push_frames(
    target: &DaemonTarget,
    frames: &[crate::image_proc::Frame],
    mac: Option<&str>,
) -> Result<(), String> {
    let Some((_, w, h, _)) = frames.first() else {
        return Err("the image decoded to no frames".into());
    };
    let wire: Vec<Value> = frames
        .iter()
        .map(|(rgb, _, _, time_ms)| {
            json!({
                "rgb_b64": base64::engine::general_purpose::STANDARD.encode(rgb),
                "time_ms": time_ms,
            })
        })
        .collect();
    crate::mcp_daemon::dc_kw(
        target,
        "show_image",
        json!({ "w": w, "h": h, "frames": wire }),
        mac,
    )
    .await?;
    Ok(())
}

#[cfg(test)]
#[path = "mcp_tools_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "mcp_tools_image_tests.rs"]
mod image_tests;
