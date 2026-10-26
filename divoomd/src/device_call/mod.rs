mod args;
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::Request;
use crate::protocol::{
    err_code, err_with,
    ErrorCode::{BadRequest, DeviceDisconnected, DeviceFailed, Unsupported},
};
use serde_json::Value;
use std::time::Duration;

pub struct CallCtx<'a> {
    pub daemon: &'a Daemon,
    pub dev: &'a DeviceTransport,
    pub args: &'a [i64],
    pub raw_args: &'a [Value],
    pub kwargs: Option<&'a serde_json::Map<String, Value>>,
    pub blob_map: &'a std::sync::Mutex<std::collections::HashMap<usize, Vec<u8>>>,
    pub timeout: Duration,
    /// Where a handler that streamed frames leaves them (WG.5a).
    pub shown: &'a crate::device::screen::Sink,
}

pub mod aid_sleep;
pub mod alarm;
pub mod animation;
pub mod basic;
pub mod design;
pub mod drawing;
pub mod game;
mod lan;
pub mod music;
pub(crate) mod read;
pub mod routing;
pub mod sleep;
pub mod system;
mod system_sound;
pub mod text;
pub mod timeplan;
pub mod tools;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};

pub(crate) use args::{pos_bool, pos_i64, rgb_triple};

fn decode_blob_map(req: &Request) -> Result<std::collections::HashMap<usize, Vec<u8>>, String> {
    let mut map = std::collections::HashMap::new();
    if let Some(blobs) = req.args.get("blobs").and_then(|v| v.as_object()) {
        for (idx_str, b64val) in blobs {
            let idx: usize = match idx_str.parse() {
                Ok(i) => i,
                Err(_) => return Err(format!("blobs: bad index key '{idx_str}'")),
            };
            let Some(b64) = b64val.as_str() else {
                return Err(format!("blobs[{idx_str}]: not a string"));
            };
            match B64.decode(b64) {
                Ok(data) => {
                    map.insert(idx, data);
                }
                Err(e) => return Err(format!("blobs[{idx_str}]: base64 error: {e}")),
            }
        }
    }
    Ok(map)
}

fn report_no_lan(dev: &DeviceTransport) -> Value {
    let (cause, why) = match dev {
        DeviceTransport::Spp(_) => (
            "no_lan_capability",
            "this device is connected over Bluetooth, which has no LAN API",
        ),
        #[cfg(feature = "ble")]
        DeviceTransport::Ble(_) => (
            "no_lan_capability",
            "this device is connected over Bluetooth, which has no LAN API",
        ),
        _ => (
            "not_configured",
            "no LAN address is configured for this device",
        ),
    };
    // `cause` says which of the two it is; the code says no retry will help.
    err_with(Unsupported, why, serde_json::json!({ "cause": cause }))
}

/// The reply for a command that could not be sent: the link is gone.
///
/// A write that fails IS the link failing -- the command never left the
/// machine -- so the panel is not connected, and the code says so (P2.8).
/// `device_failed` is for the other thing: a panel that IS there and did not
/// do what was asked (it did not answer, or it answered with something the
/// daemon could not read).
///
/// The daemon acts on the code: a `device_disconnected` reply retires the
/// link and reports the drop, so the panel stops reading as connected.
pub(crate) fn link_gone(what: &str, e: &impl std::fmt::Display) -> Value {
    err_code(DeviceDisconnected, &format!("{what} failed: {e}"))
}

async fn handle_lan_fallback(
    lan_dev: &crate::lan::LanTransport,
    method: &str,
    args: &[i64],
    raw_args: &[Value],
    req: &Request,
) -> Value {
    let res = if matches!(
        method,
        "system.set_screen_on" | "device.set_screen_on" | "set_screen_on" | "display.set_screen_on"
    ) {
        let on = raw_args
            .first()
            .and_then(|v| v.as_bool().or_else(|| v.as_i64().map(|n| n != 0)))
            .or_else(|| {
                req.args
                    .get("kwargs")
                    .and_then(|m| {
                        m.get("on")
                            .or_else(|| m.get("OnOff"))
                            .or_else(|| m.get("screen_on"))
                    })
                    .and_then(|v| v.as_bool().or_else(|| v.as_i64().map(|n| n != 0)))
            })
            .unwrap_or(true);
        lan_dev
            .post(
                "Channel/OnOffScreen",
                Some(serde_json::json!({ "OnOff": i32::from(on) })),
            )
            .await
    } else if matches!(
        method,
        "system.set_brightness"
            | "device.set_brightness"
            | "set_brightness"
            | "display.set_brightness"
    ) {
        let val = args
            .first()
            .copied()
            .or_else(|| {
                req.args
                    .get("kwargs")
                    .and_then(|m| m.get("brightness").or_else(|| m.get("Brightness")))
                    .and_then(serde_json::Value::as_i64)
            })
            .unwrap_or(100);
        lan_dev
            .post(
                "Channel/SetBrightness",
                Some(serde_json::json!({ "Brightness": val })),
            )
            .await
    } else {
        return err_code(Unsupported, "method only supported on a BLE/SPP device");
    };
    match res {
        Ok(val) => serde_json::json!({ "success": true, "result": val }),
        Err(e) => err_code(DeviceFailed, &e.to_string()),
    }
}

pub async fn handle_device_call(
    daemon: &Daemon,
    dev: &DeviceTransport,
    req: &Request,
    timeout: Duration,
    shown: &crate::device::screen::Sink,
) -> Value {
    let Some(method) = req.args.get("method").and_then(|v| v.as_str()) else {
        return crate::command_args::missing("device_call", "'method'");
    };

    let args: Vec<i64> = req
        .args
        .get("args")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(serde_json::Value::as_i64).collect())
        .unwrap_or_default();

    let raw_args: Vec<Value> = req
        .args
        .get("args")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let blob_map_raw = match decode_blob_map(req) {
        Ok(m) => m,
        Err(e) => return err_code(BadRequest, &e),
    };
    let blob_map = std::sync::Mutex::new(blob_map_raw);

    if method.starts_with("lan.") {
        if let Some(lan_dev) = dev.lan() {
            let kwargs = req.args.get("kwargs").and_then(|v| v.as_object());
            return lan::handle_lan_call(lan_dev, method, &args, kwargs).await;
        }
        return report_no_lan(dev);
    }

    if let Some(lan_dev) = dev.lan() {
        return handle_lan_fallback(lan_dev, method, &args, &raw_args, req).await;
    }

    let kwargs = req.args.get("kwargs").and_then(|v| v.as_object());
    let ctx = CallCtx {
        daemon,
        dev,
        args: &args,
        raw_args: &raw_args,
        kwargs,
        blob_map: &blob_map,
        timeout,
        shown,
    };

    routing::route(method, ctx).await
}
