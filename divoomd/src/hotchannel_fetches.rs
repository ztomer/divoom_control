//! What the category actually returned, written down with a date on it.
//!
//! # The question this exists to answer
//!
//! The owner asked whether the "monthly best" gallery is a sliding window and
//! said they were not sure. That is a MEASUREMENT question, and the honest
//! answer was not available from the code or from a belief: it needs two dated
//! snapshots of the same category and a diff.
//!
//! So every run records what came back — the file list, with the date each
//! file carries and the name it is published under — into the daemon's log AND
//! into a dated snapshot file. Two snapshots a day apart answer the question
//! either way; a snapshot that only ever holds one list answers it never.
//!
//! The snapshot file keeps the last few runs so a diff is a diff of two
//! entries, not of a log file that has been rotated away.

use serde_json::{json, Value};
use std::path::PathBuf;

/// How many runs the snapshot file keeps.
const KEEP_RUNS: usize = 14;

/// One file the category offered.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FetchedFile {
    /// The name the cloud publishes it under (it often carries a date itself).
    pub name: String,
    /// The date the cloud says the file was made, as `YYYY-MM-DD`.
    pub date: String,
    /// The cloud's file id — the stable identity of this piece of art.
    pub id: String,
    /// Who published it.
    pub user: String,
}

/// One run's fetch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FetchRun {
    /// When the fetch happened (`YYYY-MM-DDTHH:MM:SSZ`).
    pub at: String,
    /// The gallery classify that was fetched.
    pub classify: i64,
    /// The device the fetch was for.
    pub address: String,
    /// What came back.
    pub files: Vec<FetchedFile>,
}

/// Where the snapshots live.
#[must_use]
pub fn snapshot_path() -> Option<PathBuf> {
    Some(crate::cloud::config_dir()?.join("hotchannel_fetches.json"))
}

/// The files a category response offered, in the order the cloud listed them.
///
/// Pure, so the shape of the cloud's answer can be pinned by a test instead
/// of by a run against the live API.
#[must_use]
pub fn files_from_response(response: &Value) -> Vec<FetchedFile> {
    let Some(list) = response.get("FileList").and_then(Value::as_array) else {
        return Vec::new();
    };
    list.iter()
        .map(|item| FetchedFile {
            name: item
                .get("FileName")
                .and_then(Value::as_str)
                .unwrap_or("unnamed")
                .trim()
                .to_string(),
            date: item
                .get("Date")
                .and_then(Value::as_i64)
                .map_or_else(String::new, |d| {
                    crate::civil_time::iso_date(u64::try_from(d).unwrap_or(0))
                }),
            id: item
                .get("FileId")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            user: item
                .get("UserName")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
        })
        .collect()
}

/// Record one run's fetch in the snapshot file.
///
/// # Errors
///
/// When the snapshot file cannot be written.
pub fn record_fetch(classify: i64, address: &str, files: &[FetchedFile]) -> Result<(), String> {
    let Some(path) = snapshot_path() else {
        return Err("no config directory to record the fetch in".to_string());
    };
    let run = json!({
        "at": crate::civil_time::iso_timestamp(crate::civil_time::unix_seconds()),
        "classify": classify,
        "address": address,
        "files": files.iter().map(|f| json!({
            "name": f.name,
            "date": f.date,
            "id": f.id,
            "user": f.user,
        })).collect::<Vec<Value>>(),
    });

    let mut runs = load_runs();
    runs.insert(0, run);
    runs.truncate(KEEP_RUNS);

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&json!({"runs": runs})).map_err(|e| e.to_string())?;
    std::fs::write(&path, text + "\n").map_err(|e| e.to_string())
}

/// The recorded runs, newest first.
#[must_use]
pub fn load_runs() -> Vec<Value> {
    let Some(path) = snapshot_path() else {
        return Vec::new();
    };
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Vec::new();
    };
    let Ok(value) = serde_json::from_str::<Value>(&text) else {
        return Vec::new();
    };
    value
        .get("runs")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_files_come_back_with_the_dates_they_carry() {
        let response = json!({
            "FileList": [
                {"FileName": "Birds2022+mountain ", "Date": 1_658_786_869, "FileId": "group1/M00/10/B2/x", "UserName": "Ush"},
                {"FileName": "unnamed one", "FileId": "group1/M00/07/07/y"},
            ]
        });
        let files = files_from_response(&response);
        assert_eq!(files.len(), 2);
        assert_eq!(files[0].name, "Birds2022+mountain");
        assert_eq!(files[0].date, "2022-07-25");
        assert_eq!(files[0].user, "Ush");
        assert_eq!(files[1].date, "");
    }

    #[test]
    fn a_response_with_no_file_list_is_no_files() {
        assert_eq!(files_from_response(&json!({"ReturnCode": 0})).len(), 0);
    }
}
