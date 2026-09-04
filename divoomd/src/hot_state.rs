//! Per-device HOT-channel last-checked state (R53).
//!
//! The daemon owns this: it runs the hot-channel update and knows the outcome +
//! target device firsthand, so it stamps `hot_update_state.json` on completion.
//! The GUI only reads it. Mirrors `divoom_lib/hot_update_state.py` — the JSON
//! file is the shared contract between this native daemon, the Python fallback
//! daemon, and the GUI.
//!
//! Shape (keyed by the GUI's device address — MAC, `LAN:<ip>`, or `MatrixWall`):
//!
//! ```text
//! { "AA:BB:CC:DD:EE:FF": { "checked_at": 1720000000, "served": 0,
//!                          "manifest": 12, "downloaded": 12, "confirmed": 0 } }
//! ```

use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

fn state_path() -> Option<PathBuf> {
    // Honor an override (parity with the Python module) without a separate
    // config surface.
    if let Ok(p) = std::env::var("DIVOOM_HOT_STATE") {
        return Some(PathBuf::from(p));
    }
    let mut dir = crate::cloud::config_dir()?;
    dir.push("hot_update_state.json");
    Some(dir)
}

fn load_map(path: &Path) -> serde_json::Map<String, Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

/// Record the outcome of a hot-channel check for `address`, keyed as-is (the GUI
/// reads by the same address string it passed in). `summary` is
/// `run_hot_update`'s result dict. No-op on a blank address; never panics.
pub fn record_check(address: &str, summary: &Value) -> Result<(), String> {
    match state_path() {
        Some(path) => record_check_at(&path, address, summary),
        None => Err("cannot find config directory".into()),
    }
}

/// Path-explicit core (unit-testable without touching process-global env).
fn record_check_at(path: &Path, address: &str, summary: &Value) -> Result<(), String> {
    if address.is_empty() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    // `served` arrives as an array in the raw result; tolerate an int too.
    let served = match summary.get("served") {
        Some(Value::Array(a)) => a.len() as u64,
        Some(v) => v.as_u64().unwrap_or(0),
        None => 0,
    };
    let get_u = |k: &str| summary.get(k).and_then(|v| v.as_u64()).unwrap_or(0);
    let checked_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);

    let mut map = load_map(path);
    map.insert(
        address.to_string(),
        json!({
            "checked_at": checked_at,
            "served": served,
            "manifest": get_u("manifest"),
            "downloaded": get_u("downloaded"),
            "confirmed": get_u("confirmed"),
        }),
    );

    let data = serde_json::to_string_pretty(&Value::Object(map)).map_err(|e| e.to_string())?;
    let temp_path = path.with_extension("json.tmp");
    std::fs::write(&temp_path, data).map_err(|e| e.to_string())?;
    std::fs::rename(temp_path, path).map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    #[test]
    fn records_and_reads_back() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("hot_update_state.json");
        let summary = json!({
            "success": true,
            "served": [{"file_id": "x"}],
            "manifest": 12, "downloaded": 10, "confirmed": 1
        });
        record_check_at(&path, "AA:BB:CC:DD:EE:FF", &summary).unwrap();
        let map = load_map(&path);
        let e = &map["AA:BB:CC:DD:EE:FF"];
        assert_eq!(e["served"].as_u64().unwrap(), 1);
        assert_eq!(e["manifest"].as_u64().unwrap(), 12);
        assert_eq!(e["downloaded"].as_u64().unwrap(), 10);
        assert_eq!(e["confirmed"].as_u64().unwrap(), 1);
        assert!(e["checked_at"].as_u64().unwrap() > 0);
    }

    #[test]
    fn blank_address_is_noop() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("hot_update_state.json");
        record_check_at(&path, "", &json!({"manifest": 5})).unwrap();
        assert!(load_map(&path).is_empty());
    }

    #[test]
    fn per_device_keying_overwrites_same_device() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("hot_update_state.json");
        record_check_at(
            &path,
            "dev1",
            &json!({"served": [1], "manifest": 3, "downloaded": 3}),
        )
        .unwrap();
        record_check_at(
            &path,
            "dev2",
            &json!({"served": [], "manifest": 3, "downloaded": 3}),
        )
        .unwrap();
        record_check_at(
            &path,
            "dev1",
            &json!({"served": [], "manifest": 3, "downloaded": 3}),
        )
        .unwrap();
        let map = load_map(&path);
        assert_eq!(map.len(), 2);
        assert_eq!(map["dev1"]["served"].as_u64().unwrap(), 0); // overwritten, not appended
        assert_eq!(map["dev2"]["served"].as_u64().unwrap(), 0);
    }
}
