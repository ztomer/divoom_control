//! Divoom cloud playlist endpoints.
//! Split out of `cloud_category.rs` to keep files under the 500-line house
//! limit. Ported from `divoom_lib/cloud.py`.

use serde_json::{json, Value};
use std::time::Duration;

use crate::cloud::{
    get_credentials, load_virtual_device, DivoomCredentials, BASE_URL, TIMEOUT_SECS,
};

// ── Playlist browse + push to device ────────────────────────────────────
//
// Confirmed LIVE working 2026-07-14 (real logged-in account, RC=0). Pushing
// a playlist to the connected device is NOT a cloud call — see
// `device_call::mod::lan.send_playlist` (`Playlist/SendDevice` posted
// directly to the device's own LAN IP, same mechanism as `lan.set_clock`).

/// List the current user's cloud-hosted playlists (`PlayId`/`Name`/`Count`/…).
pub async fn get_my_playlists(limit: i64, page: i64) -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw, _, _) = load_virtual_device();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let start = (page - 1) * limit + 1;
    let end = page * limit;
    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": "Playlist/GetMyList",
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
            "StartNum": start,
            "EndNum": end,
        });
        if device_pw != 0 {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("DevicePassword".to_string(), json!(device_pw));
            }
        }
        body
    };

    let url = format!("{}/Playlist/GetMyList", BASE_URL);
    let mut req_body = make_request(&creds);
    let mut resp = client
        .post(&url)
        .json(&req_body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let mut data: Value = resp.json().await.map_err(|e| e.to_string())?;
    let mut rc = data
        .get("ReturnCode")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);

    if rc == 9 || rc == 10 || rc == 11 {
        creds = get_credentials(true).await?;
        req_body = make_request(&creds);
        resp = client
            .post(&url)
            .json(&req_body)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        data = resp.json().await.map_err(|e| e.to_string())?;
        rc = data
            .get("ReturnCode")
            .and_then(|v| v.as_i64())
            .unwrap_or(-1);
    }

    if rc != 0 {
        let msg = data
            .get("ReturnMessage")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown cloud error");
        return Err(format!("Playlist/GetMyList failed (RC={rc}): {msg}"));
    }
    Ok(data
        .get("PlayList")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}

/// List the images/animations inside one of the user's own playlists.
pub async fn get_playlist_images(play_id: i64, limit: i64, page: i64) -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw, _, _) = load_virtual_device();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let start = (page - 1) * limit + 1;
    let end = page * limit * 2;
    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": "Playlist/GetMyImageList",
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
            "PlayId": play_id,
            "FileSort": 0,
            "FileType": 5,
            "FileSize": 0,
            "Version": 19,
            "StartNum": start,
            "EndNum": end,
            "RefreshIndex": 0,
        });
        if device_pw != 0 {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("DevicePassword".to_string(), json!(device_pw));
            }
        }
        body
    };

    let url = format!("{}/Playlist/GetMyImageList", BASE_URL);
    let mut req_body = make_request(&creds);
    let mut resp = client
        .post(&url)
        .json(&req_body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let mut data: Value = resp.json().await.map_err(|e| e.to_string())?;
    let mut rc = data
        .get("ReturnCode")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);

    if rc == 9 || rc == 10 || rc == 11 {
        creds = get_credentials(true).await?;
        req_body = make_request(&creds);
        resp = client
            .post(&url)
            .json(&req_body)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        data = resp.json().await.map_err(|e| e.to_string())?;
        rc = data
            .get("ReturnCode")
            .and_then(|v| v.as_i64())
            .unwrap_or(-1);
    }

    if rc != 0 {
        let msg = data
            .get("ReturnMessage")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown cloud error");
        return Err(format!("Playlist/GetMyImageList failed (RC={rc}): {msg}"));
    }
    Ok(data
        .get("FileList")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}
