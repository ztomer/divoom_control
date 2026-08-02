//! Photo-frame album browse (`Photo/GetAlbumList`) — split out to keep
//! `cloud_category.rs` under the 500-line house limit. Ported from
//! `divoom_lib/cloud.py`'s `get_photo_albums`.
//!
//! Not in `HttpCommand.DeviceAndServerCmd`/`ForceDeviceHttp` (see
//! docs/cloud_api/photo_discover.md), so this is a plain cloud call, same
//! auth-retry pattern as `Playlist/GetMyList`. Applying a selected album
//! (`Photo/PlayAlbum`) is a separate, LAN-only device call — see
//! `device_call::mod::handle_lan_call`'s `lan.play_album`.

use serde_json::{json, Value};
use std::time::Duration;

use crate::cloud::{
    get_credentials, load_virtual_device, DivoomCredentials, BASE_URL, TIMEOUT_SECS,
};

/// List the photo albums ("clocks") configured for the active device.
pub async fn get_photo_albums() -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw, _, _) = load_virtual_device();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": "Photo/GetAlbumList",
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
        });
        if device_pw != 0 {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("DevicePassword".to_string(), json!(device_pw));
            }
        }
        body
    };

    let url = format!("{}/Photo/GetAlbumList", BASE_URL);
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
        return Err(format!("Photo/GetAlbumList failed (RC={rc}): {msg}"));
    }
    Ok(data
        .get("AlbumList")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}
