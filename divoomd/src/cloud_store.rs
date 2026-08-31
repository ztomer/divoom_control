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
/// Rewrite only the `email`/`password` keys of `[divoom]`, line by line.
///
/// Hand-rolled to match `load_config` above, which is also hand-rolled: adding
/// an ini crate for the writer while the reader stays bespoke would give one
/// file two parsers with different ideas about it, which is the shape R72
/// exists to remove.
fn merge_divoom_section(existing: &str, email: &str, password: &str) -> String {
    let keep_password = password.is_empty();
    let mut out: Vec<String> = Vec::new();
    let mut in_divoom = false;
    let mut saw_section = false;
    let mut wrote_email = false;
    let mut wrote_password = false;

    for line in existing.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            if in_divoom {
                if !wrote_email {
                    out.push(format!("email = {email}"));
                    wrote_email = true;
                }
                if !wrote_password && !keep_password {
                    out.push(format!("password = {password}"));
                    wrote_password = true;
                }
            }
            in_divoom = trimmed[1..trimmed.len() - 1].eq_ignore_ascii_case("divoom");
            saw_section |= in_divoom;
            out.push(line.to_string());
            continue;
        }
        if in_divoom {
            let key = trimmed.split('=').next().unwrap_or("").trim().to_ascii_lowercase();
            if key == "email" {
                out.push(format!("email = {email}"));
                wrote_email = true;
                continue;
            }
            if key == "password" {
                if keep_password {
                    out.push(line.to_string());
                } else {
                    out.push(format!("password = {password}"));
                }
                wrote_password = true;
                continue;
            }
        }
        out.push(line.to_string());
    }

    if in_divoom {
        if !wrote_email {
            out.push(format!("email = {email}"));
        }
        if !wrote_password && !keep_password {
            out.push(format!("password = {password}"));
        }
    } else if !saw_section {
        if !out.is_empty() && !out.last().map(|l| l.is_empty()).unwrap_or(false) {
            out.push(String::new());
        }
        out.push("[divoom]".to_string());
        out.push(format!("email = {email}"));
        if !keep_password {
            out.push(format!("password = {password}"));
        }
    }

    let mut joined = out.join("\n");
    joined.push('\n');
    joined
}

/// Update `[divoom]` in config.ini, PRESERVING every other section.
///
/// R72 P1.1. This used to write the whole file as
/// `"[divoom]\nemail=..\npassword=..\n"`, destroying `[gui]`, `[gallery]`
/// and the weather settings that share it. Nothing had noticed because no
/// client called it -- the GUI did its own read-modify-write through
/// configparser -- so the daemon's version was a second implementation that
/// had never run in anger. Routing the GUI here, which the capability map
/// called for, would have eaten the user's settings on the first save.
///
/// An EMPTY password means "keep the stored one", the second thing the Python
/// side knew and this did not. The settings form never re-populates the
/// password field, so a plain re-save submits `password=""`; overwriting with
/// that erased the credential and the next token expiry silently degraded the
/// account to a guest login -- described in `presets_manager.py` as
/// "credentials get erased from time to time". Not reintroduced here.
pub fn save_config(email: &str, password: &str) -> Result<(), String> {
    let path = config_file_path().ok_or("cannot find config directory")?;
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let existing = std::fs::read_to_string(&path).unwrap_or_default();
    let data = merge_divoom_section(&existing, email.trim(), password);
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

#[cfg(test)]
mod merge_tests {
    use super::merge_divoom_section;

    // These guard a DATA-LOSS path. The version this replaced wrote the whole
    // file as "[divoom]\nemail=..\npassword=..\n", so every other section went
    // with it. Nothing had noticed because no client called it -- the GUI did
    // its own read-modify-write -- and the capability map's verdict was to
    // route the GUI here, which would have eaten the user's settings on the
    // first save.

    #[test]
    fn other_sections_survive() {
        let before = "[gui]\ntimeout = 120\nlimit = 4\n\n\
                      [divoom]\nemail = old@x.com\npassword = secret\n\n\
                      [gallery]\ngallery_sort = 1\n";
        let after = merge_divoom_section(before, "new@x.com", "hunter2");
        assert!(after.contains("[gui]"), "{after}");
        assert!(after.contains("timeout = 120"), "{after}");
        assert!(after.contains("[gallery]"), "{after}");
        assert!(after.contains("gallery_sort = 1"), "{after}");
        assert!(after.contains("email = new@x.com"), "{after}");
        assert!(after.contains("password = hunter2"), "{after}");
    }

    #[test]
    fn an_empty_password_keeps_the_stored_one() {
        // The settings form never re-populates the password field, so a plain
        // re-save submits "". Overwriting with that erased the credential and
        // the next token expiry degraded the account to a guest login.
        let before = "[divoom]\nemail = old@x.com\npassword = secret\n";
        let after = merge_divoom_section(before, "new@x.com", "");
        assert!(after.contains("password = secret"), "password was wiped: {after}");
        assert!(after.contains("email = new@x.com"), "{after}");
        assert!(!after.contains("old@x.com"), "{after}");
    }

    #[test]
    fn a_missing_divoom_section_is_appended_without_touching_the_rest() {
        let before = "[gui]\ntimeout = 120\n";
        let after = merge_divoom_section(before, "a@b.com", "pw");
        assert!(after.contains("[gui]"), "{after}");
        assert!(after.contains("timeout = 120"), "{after}");
        assert!(after.contains("[divoom]"), "{after}");
        assert!(after.contains("email = a@b.com"), "{after}");
    }

    #[test]
    fn an_empty_file_gets_a_whole_section() {
        let after = merge_divoom_section("", "a@b.com", "pw");
        assert!(after.contains("[divoom]"), "{after}");
        assert!(after.contains("email = a@b.com"), "{after}");
        assert!(after.contains("password = pw"), "{after}");
    }

    #[test]
    fn a_divoom_section_missing_a_key_gains_it() {
        let before = "[divoom]\nemail = a@b.com\n\n[gui]\ntimeout = 5\n";
        let after = merge_divoom_section(before, "a@b.com", "pw");
        assert!(after.contains("password = pw"), "{after}");
        assert!(after.contains("[gui]"), "section order broken: {after}");
        assert!(after.contains("timeout = 5"), "{after}");
    }

    #[test]
    fn keys_outside_divoom_are_never_rewritten() {
        let before = "[other]\nemail = do-not-touch\n\n[divoom]\nemail = a@b.com\n";
        let after = merge_divoom_section(before, "new@x.com", "");
        assert!(after.contains("email = do-not-touch"), "{after}");
        assert!(after.contains("email = new@x.com"), "{after}");
    }

    #[test]
    fn the_file_ends_with_exactly_one_newline() {
        let after = merge_divoom_section("[divoom]\nemail = a@b.com\n", "b@c.com", "");
        assert!(after.ends_with('\n'), "{after:?}");
        assert!(!after.ends_with("\n\n"), "{after:?}");
    }
}
