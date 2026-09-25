//! MCP tool catalog + dispatch.
//!
//! Ported from `divoom_lib/mcp_tools.py`. Each tool forwards to the daemon as a
//! `device_call` (or top-level command) over the local unix socket or a remote
//! TCP connection (`crate::daemon_target`); file-based tools decode locally (the
//! `image` crate) and push rgb.

use base64::Engine;
use serde_json::{json, Value};

use crate::daemon_target::DaemonTarget;

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
        tool("show_image", "Push a local image file to the device.",
            &json!({"type":"object","properties":{"file":{"type":"string","description":"Local filesystem path to the image."}},"required":["file"]})),
        tool("push_animation", "Push a GIF/animation to the device. Provide 'file' (path) or 'data' (base64). First frame for now.",
            &json!({"type":"object","properties":{"file":{"type":"string"},"data":{"type":"string"}},"oneOf":[{"required":["file"]},{"required":["data"]}]})),
        tool("play_sound", "Beep the device (best-effort; some firmware no-ops).",
            &json!({"type":"object","properties":{"duration_ms":int(100,3000)},"required":["duration_ms"]})),
        tool("get_capabilities", "Read the device's static capabilities / connection state.",
            &json!({"type":"object","properties":{},"additionalProperties":false})),
        tool("get_device_state", "Read the device's current volume, brightness, channel, orientation, mirror.",
            &json!({"type":"object","properties":{},"additionalProperties":false})),
        tool("list_screens", "List all known and connected display screens, their resolutions, spatial coordinates, rooms, and wall grouping.",
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
        "get_capabilities" => crate::mcp_daemon::cmd(target, "device_status", json!({})).await,
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

async fn set_weather(a: &Value, target: &DaemonTarget) -> Result<Value, String> {
    let mac = a.get("mac").and_then(Value::as_str);

    let temp = need_int(a, "temperature_c", -127, 128)?;
    let weather = a
        .get("weather")
        .and_then(|v| v.as_str())
        .ok_or("weather must be a string")?;
    let wt = WEATHER_TYPES
        .iter()
        .find(|(n, _)| *n == weather)
        .map(|(_, t)| *t)
        .ok_or_else(|| {
            format!(
                "weather must be one of {:?}",
                WEATHER_TYPES.iter().map(|(n, _)| *n).collect::<Vec<_>>()
            )
        })?;
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

    let file = a
        .get("file")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("file must be a non-empty local path string")?;
    let bytes = std::fs::read(file).map_err(|e| format!("cannot read {file}: {e}"))?;
    push_image_bytes(target, &bytes, mac).await?;
    Ok(json!({ "ok": true, "file": file }))
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
    push_image_bytes(target, &bytes, mac).await?;
    Ok(
        json!({ "ok": true, "note": "pushed first frame (full animation streaming is a follow-up)" }),
    )
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

fn need_int(a: &Value, key: &str, lo: i64, hi: i64) -> Result<i64, String> {
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

/// Decode image bytes (PNG/JPG/GIF first frame) to a 16x16 RGB frame and push it
/// via the daemon's `show_image` (rgb kwargs). Device size is 16 for now.
async fn push_image_bytes(
    target: &DaemonTarget,
    bytes: &[u8],
    mac: Option<&str>,
) -> Result<(), String> {
    let img = image::load_from_memory(bytes).map_err(|e| format!("decode failed: {e}"))?;
    let small = img
        .resize_exact(16, 16, image::imageops::FilterType::Nearest)
        .to_rgb8();
    let rgb: Vec<u8> = small.into_raw();
    crate::mcp_daemon::dc_kw(
        target,
        "show_image",
        json!({ "w": 16, "h": 16, "time_ms": 100, "rgb": rgb }),
        mac,
    )
    .await?;
    Ok(())
}

#[cfg(test)]
#[path = "mcp_tools_tests.rs"]
mod tests;
