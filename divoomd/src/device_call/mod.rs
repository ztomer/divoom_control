mod args;
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::Request;
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
pub mod routing;
pub mod sleep;
pub mod system;
pub mod text;
pub mod timeplan;
pub mod tools;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};

pub(crate) use args::{pos_bool, pos_i64};

pub async fn handle_device_call(
    _daemon: &Daemon,
    dev: &DeviceTransport,
    req: &Request,
    _timeout: Duration,
) -> Value {
    let method = match req.args.get("method").and_then(|v| v.as_str()) {
        Some(m) => m,
        None => return crate::protocol::err_reply("device_call requires 'method'"),
    };

    // Numeric positional args (for brightness, clock, etc.).
    //
    // WARNING (R67/C7): this list is COMPACTED — `filter_map` drops every
    // non-numeric entry, so `args[i]` is the i-th NUMBER, not the i-th
    // ARGUMENT. For a call like show_light("#00FFCC", 80, true, 2) it is
    // [80, 2], and `args.get(1)` yields the mode, not the brightness. That
    // silently swapped ambient brightness for the mode number on real hardware
    // until a wire trace caught it.
    //
    // Use `pos_i64()` for anything positional. `args` is retained only for
    // handlers whose arguments are all numeric, where the two agree.
    let args: Vec<i64> = req
        .args
        .get("args")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
        .unwrap_or_default();

    // Raw positional args as Values (for string paths in display.show_image)
    let raw_args: Vec<Value> = req
        .args
        .get("args")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    // Blob map: base64-encoded binary data keyed by positional arg index.
    let mut blob_map_raw: std::collections::HashMap<usize, Vec<u8>> =
        std::collections::HashMap::new();
    if let Some(blobs) = req.args.get("blobs").and_then(|v| v.as_object()) {
        for (idx_str, b64val) in blobs {
            let idx: usize = match idx_str.parse() {
                Ok(i) => i,
                Err(_) => {
                    return crate::protocol::err_reply(&format!("blobs: bad index key '{idx_str}'"))
                }
            };
            let b64 = match b64val.as_str() {
                Some(s) => s,
                None => {
                    return crate::protocol::err_reply(&format!("blobs[{idx_str}]: not a string"))
                }
            };
            match B64.decode(b64) {
                Ok(data) => {
                    blob_map_raw.insert(idx, data);
                }
                Err(e) => {
                    return crate::protocol::err_reply(&format!(
                        "blobs[{idx_str}]: base64 error: {e}"
                    ))
                }
            }
        }
    }
    let blob_map = std::sync::Mutex::new(blob_map_raw);

    if method.starts_with("lan.") {
        if let Some(lan_dev) = dev.lan() {
            let kwargs = req.args.get("kwargs").and_then(|v| v.as_object());
            return lan::handle_lan_call(lan_dev, method, &args, kwargs).await;
        } else {
            // R71 P3.1: say WHY, with a machine-readable cause.
            //
            // "device is not connected via LAN" was accurate and useless: the
            // GUI collapsed it to a bare false and the user saw "Failed to send
            // overlay", which reads as a broken feature rather than "this model
            // has no LAN". Same defect R70 fixed for cloud browse, unfixed on
            // this side. `cause` is a flag, never parsed text, so the wording
            // can change without moving the UI.
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
            let mut reply = crate::protocol::err_reply(why);
            if let Value::Object(ref mut m) = reply {
                m.insert("cause".into(), Value::String(cause.into()));
            }
            return reply;
        }
    }

    // LAN devices are handled above; everything else (BLE / SPP / Mock) routes
    // through the build-agnostic DeviceTransport method layer.
    {
        if !matches!(dev, DeviceTransport::Lan(_)) {
            let kwargs = req.args.get("kwargs").and_then(|v| v.as_object());
            let ctx = CallCtx {
                daemon: _daemon,
                dev,
                args: &args,
                raw_args: &raw_args,
                kwargs,
                blob_map: &blob_map,
                timeout: _timeout,
            };

            routing::route(method, ctx).await
        } else {
            crate::protocol::err_reply("method only supported on a BLE/SPP device")
        }
    }
}
