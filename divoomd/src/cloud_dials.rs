//! Clock faces: the dial types a device offers, and the dials in each.
//!
//! Split out of `cloud_category` for the house 500-line cap, along a seam that
//! was already there -- these three calls are the `Channel/GetDial*` family and
//! share no state with the gallery, weather-city or sleep-list calls.
//!
//! # Cloud errors
//!
//! As in `cloud_category`: the HTTP request cannot be sent or its body is not
//! the JSON shape expected, or the API answers a non-zero return code. The
//! message carries the RC and the server's own text.

use std::time::Duration;

use serde_json::{json, Value};

use super::cloud::{BASE_URL, TIMEOUT_SECS};

/// Fetch the clock-face store's category names (`Channel/GetDialType`).
///
/// # Errors
///
/// See the module note on cloud errors.
pub async fn get_dial_types() -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let url = format!("{BASE_URL}/Channel/GetDialType");
    let resp = client
        .post(&url)
        .json(&json!({}))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let data: Value = resp.json().await.map_err(|e| e.to_string())?;
    let rc = data
        .get("ReturnCode")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(-1);

    if rc != 0 {
        let msg = data
            .get("ReturnMessage")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown cloud error");
        return Err(format!("Channel/GetDialType failed (RC={rc}): {msg}"));
    }
    Ok(data
        .get("DialTypeList")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}

/// Fetch clock faces (`ClockId`/`Name`) for one category name.
///
/// # Errors
///
/// See the module note on cloud errors.
pub async fn get_dial_list(dial_type: &str, page: i64) -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let url = format!("{BASE_URL}/Channel/GetDialList");
    let body = json!({ "DialType": dial_type, "Page": page });
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let data: Value = resp.json().await.map_err(|e| e.to_string())?;
    let rc = data
        .get("ReturnCode")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(-1);

    if rc != 0 {
        let msg = data
            .get("ReturnMessage")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown cloud error");
        return Err(format!("Channel/GetDialList failed (RC={rc}): {msg}"));
    }
    Ok(data
        .get("DialList")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}

/// Browse the cloud clock-face store. With no `dial_type`, use the first
/// category from `get_dial_types`.
///
/// # Errors
///
/// See the module note on cloud errors.
pub async fn list_clock_faces(dial_type: Option<String>, page: i64) -> Result<Value, String> {
    let dial_type = if let Some(t) = dial_type {
        t
    } else {
        let types = get_dial_types().await?;
        match types
            .as_array()
            .and_then(|a| a.first())
            .and_then(|v| v.as_str())
        {
            Some(first) => first.to_string(),
            None => return Ok(Value::Array(vec![])),
        }
    };
    get_dial_list(&dial_type, page).await
}

// Playlist endpoints moved to `cloud_playlist.rs` to stay under the file cap.
