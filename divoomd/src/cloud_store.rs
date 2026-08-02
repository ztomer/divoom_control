//! Divoom credential persistence — config.ini (`[divoom]` email/password) + the
//! auth-token cache (auth_token.json). Split out of `cloud.rs` to keep it under
//! the 500-line house limit. Used by `cloud::get_credentials` / `save_credentials`.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::cloud::{config_dir, DivoomCredentials};

pub(crate) fn config_file_path() -> Option<PathBuf> {
    Some(config_dir()?.join("config.ini"))
}

pub(crate) fn cache_file_path() -> Option<PathBuf> {
    Some(config_dir()?.join("auth_token.json"))
}

/// Read the `[divoom]` email/password from config.ini. Returns ("","") if absent.
pub(crate) fn load_config() -> (String, String) {
    let path = match config_file_path() {
        Some(p) => p,
        None => return (String::new(), String::new()),
    };
    if !path.exists() {
        return (String::new(), String::new());
    }
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return (String::new(), String::new()),
    };
    let mut email = String::new();
    let mut password = String::new();
    let mut in_divoom_section = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            let section = &trimmed[1..trimmed.len() - 1];
            in_divoom_section = section.eq_ignore_ascii_case("divoom");
        } else if in_divoom_section {
            if let Some(pos) = trimmed.find('=') {
                let key = trimmed[..pos].trim();
                let val = trimmed[pos + 1..].trim();
                if key.eq_ignore_ascii_case("email") {
                    email = val.to_string();
                } else if key.eq_ignore_ascii_case("password") {
                    password = val.to_string();
                }
            }
        }
    }
    (email, password)
}

/// Write `[divoom]` email/password into config.ini (0600). The Rust daemon only
/// reads `[divoom]`, so a `[divoom]`-only write is safe. Mirrors the Python GUI.
pub fn save_config(email: &str, password: &str) -> Result<(), String> {
    let path = config_file_path().ok_or("cannot find config directory")?;
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let data = format!("[divoom]\nemail={}\npassword={}\n", email.trim(), password);
    let temp_path = path.with_extension("ini.tmp");
    std::fs::write(&temp_path, data).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&temp_path, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(temp_path, path).map_err(|e| e.to_string())?;
    Ok(())
}

pub(crate) fn save_cache(creds: &DivoomCredentials) -> Result<(), String> {
    let path = cache_file_path().ok_or("cannot find cache directory")?;
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
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
    let temp_path = path.with_extension("tmp");
    std::fs::write(&temp_path, data).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&temp_path, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(temp_path, path).map_err(|e| e.to_string())?;
    Ok(())
}

pub(crate) fn load_cache() -> Option<DivoomCredentials> {
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
        utc: val.get("utc").and_then(|v| v.as_i64()).unwrap_or(0),
    };
    if creds.is_valid() {
        Some(creds)
    } else {
        None
    }
}

pub(crate) fn virtual_device_file_path() -> Option<PathBuf> {
    Some(config_dir()?.join("virtual_device.json"))
}

/// Persist a freshly `BlueDevice/NewDevice`-registered device identity —
/// see `cloud::ensure_virtual_device`.
pub(crate) fn save_virtual_device(
    device_id: i64,
    device_pw: i64,
    type_: i64,
    subtype: i64,
) -> Result<(), String> {
    let path = virtual_device_file_path().ok_or("cannot find config directory")?;
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let val = json!({
        "BluetoothDeviceId": device_id,
        "DevicePassword": device_pw,
        "Type": type_,
        "SubType": subtype,
    });
    let data = serde_json::to_string_pretty(&val).map_err(|e| e.to_string())?;
    let temp_path = path.with_extension("tmp");
    std::fs::write(&temp_path, data).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&temp_path, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(temp_path, path).map_err(|e| e.to_string())?;
    Ok(())
}
