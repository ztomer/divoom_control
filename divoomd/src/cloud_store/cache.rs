//! The auth-token cache (`auth_token.json`) and the registered virtual
//! device identity (`virtual_device.json`).

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use super::{cache_file_path, write_private};
use crate::cloud::{config_dir, DivoomCredentials};

pub fn save_cache(creds: &DivoomCredentials) -> Result<(), String> {
    let path = cache_file_path().ok_or("cannot find cache directory")?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let val = json!({
        "token": creds.token,
        "user_id": creds.user_id,
        "email": creds.email,
        "utc": creds.utc,
        "saved_at": now,
    });
    let data = serde_json::to_string_pretty(&val).map_err(|e| e.to_string())?;
    write_private(&path, &data)
}

pub fn load_cache() -> Option<DivoomCredentials> {
    let path = cache_file_path()?;
    if !path.exists() {
        return None;
    }
    let content = std::fs::read_to_string(path).ok()?;
    let val: Value = serde_json::from_str(&content).ok()?;
    let saved_at = val.get("saved_at")?.as_u64()?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    if now > saved_at && now - saved_at > 23 * 3600 {
        return None;
    }
    let creds = DivoomCredentials {
        token: val.get("token")?.as_i64()?,
        user_id: val.get("user_id")?.as_i64()?,
        email: val
            .get("email")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        utc: val
            .get("utc")
            .and_then(serde_json::Value::as_i64)
            .unwrap_or(0),
    };
    if creds.is_valid() {
        Some(creds)
    } else {
        None
    }
}

pub fn virtual_device_file_path() -> Option<PathBuf> {
    Some(config_dir()?.join("virtual_device.json"))
}

/// Persist a freshly `BlueDevice/NewDevice`-registered device identity —
/// see `cloud::ensure_virtual_device`.
pub fn save_virtual_device(
    device_id: i64,
    device_pw: i64,
    type_: i64,
    subtype: i64,
) -> Result<(), String> {
    let path = virtual_device_file_path().ok_or("cannot find config directory")?;
    let val = json!({
        "BluetoothDeviceId": device_id,
        "DevicePassword": device_pw,
        "Type": type_,
        "SubType": subtype,
    });
    let data = serde_json::to_string_pretty(&val).map_err(|e| e.to_string())?;
    write_private(&path, &data)
}
