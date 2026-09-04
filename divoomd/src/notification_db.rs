//! macOS Notification Center database access: candidate DB paths, the
//! delivered-date query, and binary-plist record parsing.
//!
//! Split out of `macos_notifications.rs` (500-LOC house limit) — this is the
//! "read the DB" half; `macos_notifications.rs` keeps the monitor loop/state
//! and device-forwarding.

/// Locate the macOS Notification Center SQLite DB (varies by macOS version /
/// sandbox layout — try DARWIN_USER_DIR, then the Group Containers path).
pub fn find_notification_db_path() -> Option<std::path::PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let home_path = std::path::PathBuf::from(&home);

    // 1. Probing DARWIN_USER_DIR
    if let Ok(out) = std::process::Command::new("getconf")
        .arg("DARWIN_USER_DIR")
        .output()
    {
        if out.status.success() {
            let base_str = String::from_utf8_lossy(&out.stdout).trim().to_string();
            let base = std::path::PathBuf::from(base_str);
            for rel in &[
                "com.apple.notificationcenter/db2/db",
                "com.apple.usernotifications/db2/db",
            ] {
                let p = base.join(rel);
                if p.exists() {
                    return Some(p);
                }
            }
        }
    }

    // 2. Probing Group Containers path
    let p = home_path.join("Library/Group Containers/group.com.apple.usernoted/db2/db");
    if p.exists() {
        return Some(p);
    }

    None
}

pub fn initial_max_delivered_date(db_path: &std::path::Path) -> f64 {
    let conn = match rusqlite::Connection::open_with_flags(
        db_path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    ) {
        Ok(c) => c,
        Err(_) => return 0.0,
    };
    let mut stmt = match conn.prepare("SELECT MAX(delivered_date) FROM record") {
        Ok(s) => s,
        Err(_) => return 0.0,
    };
    let res: Result<f64, _> = stmt.query_row([], |row| row.get(0));
    res.unwrap_or(0.0)
}

pub fn fetch_new_records(
    db_path: &std::path::Path,
    last_seen: f64,
) -> Result<Vec<(Vec<u8>, f64)>, String> {
    let conn =
        rusqlite::Connection::open_with_flags(db_path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
            .map_err(|e| e.to_string())?;

    let mut stmt = conn.prepare(
        "SELECT data, delivered_date FROM record WHERE delivered_date > ? ORDER BY delivered_date ASC"
    ).map_err(|e| e.to_string())?;

    let rows = stmt
        .query_map([last_seen], |row| {
            Ok((row.get::<_, Vec<u8>>(0)?, row.get::<_, f64>(1)?))
        })
        .map_err(|e| e.to_string())?;

    let mut res = Vec::new();
    for item in rows.flatten() {
        res.push(item);
    }
    Ok(res)
}

pub fn parse_notification_record(raw: &[u8]) -> Option<(String, String, String)> {
    let val: plist::Value = plist::from_bytes(raw).ok()?;
    let dict = val.as_dictionary()?;

    let app = dict
        .get("app")
        .and_then(|v| v.as_string())
        .unwrap_or("")
        .to_string();

    let req = dict.get("req").and_then(|v| v.as_dictionary());
    let title = req
        .and_then(|d| d.get("titl"))
        .and_then(|v| v.as_string())
        .unwrap_or("")
        .to_string();
    let body = req
        .and_then(|d| d.get("body"))
        .and_then(|v| v.as_string())
        .unwrap_or("")
        .to_string();

    Some((app, title, body))
}
