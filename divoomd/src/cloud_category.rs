//! Divoom cloud gallery / category / weather endpoints.
//! Split out of `cloud.rs` to keep it under the 500-line house limit.
//! Ported from `divoom_lib/cloud.py`.

use serde_json::{json, Value};
use std::time::Duration;

use crate::cloud::{
    get_credentials, load_virtual_device, DivoomCredentials, BASE_URL, TIMEOUT_SECS,
};

/// Default "Classify" for `GetCategoryFileListV2` (the pixel-art / monthly-best
/// gallery) — matches the app's own default tab (`divoom_gui/web_ui/gallery.js`
/// falls back to 18 when no tab is selected). NOT related to the clock-face
/// store, which is a different endpoint pair — see `get_dial_types`/
/// `get_dial_list` below.
pub const DEFAULT_GALLERY_CLASSIFY: i64 = 18;

pub async fn fetch_gallery(
    classify: i64,
    limit: i64,
    file_sort: i64,
    file_size: i64,
) -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw, _, _) = load_virtual_device();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": "GetCategoryFileListV2",
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
            "Classify": classify,
            "FileSort": file_sort,
            "FileType": 5,
            "FileSize": file_size,
            "Version": 19,
            "StartNum": 1,
            "EndNum": limit * 2,
            "RefreshIndex": 0
        });
        if device_pw != 0 {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("DevicePassword".to_string(), json!(device_pw));
            }
        }
        body
    };

    let url = format!("{}/GetCategoryFileListV2", BASE_URL);
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
        return Err(format!("GetCategoryFileListV2 failed (RC={rc}): {msg}"));
    }

    Ok(data)
}

/// Browse a cloud gallery category (clock faces, animations, …). Returns the
/// file-list array from the response (mirrors `fetch_gallery` but returns the
/// raw list rather than the whole response).
pub async fn get_category_file_list(classify: i64, limit: i64) -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw, _, _) = load_virtual_device();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": "GetCategoryFileListV2",
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
            "Classify": classify,
            "FileSort": 0,
            "FileType": 5,
            "FileSize": 0,
            "Version": 19,
            "StartNum": 1,
            "EndNum": limit * 2,
            "RefreshIndex": 0,
        });
        if device_pw != 0 {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("DevicePassword".to_string(), json!(device_pw));
            }
        }
        body
    };

    let url = format!("{}/GetCategoryFileListV2", BASE_URL);
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
        return Err(format!("GetCategoryFileListV2 failed (RC={rc}): {msg}"));
    }
    let list = data
        .get("FileList")
        .cloned()
        .or_else(|| data.get("List").cloned())
        .unwrap_or(Value::Array(vec![]));
    Ok(list)
}

/// Search weather cities (Weather/SearchCity) by keyword. Returns the city list.
pub async fn search_weather_city(keyword: &str) -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw, _, _) = load_virtual_device();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": "Weather/SearchCity",
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
            "KeyWord": keyword,
        });
        if device_pw != 0 {
            if let Some(obj) = body.as_object_mut() {
                obj.insert("DevicePassword".to_string(), json!(device_pw));
            }
        }
        body
    };

    let url = format!("{}/Weather/SearchCity", BASE_URL);
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

    // Same expired-token family (RC 9/10/11) that fetch_gallery/get_category_file_list
    // already retry on — this endpoint was missing the self-heal.
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
        return Err(format!("Weather/SearchCity failed (RC={rc}): {msg}"));
    }
    let list = data
        .get("CityList")
        .cloned()
        .or_else(|| data.get("List").cloned())
        .unwrap_or(Value::Array(vec![]));
    Ok(list)
}

// ── clock-face store (Channel/GetDialType + Channel/GetDialList) ───────────
//
// This is Divoom's PUBLIC developer API (doc.divoom-gz.com/web/#/12?
// page_id=190), not part of HttpCommand.java's phone-app-internal command
// catalog — confirmed live 2026-07-13 (real ClockId/Name data returned) and
// requires NO auth at all (no Token/UserId/DeviceId in the request). Field
// names/URL paths confirmed against the independent r12f/divoom Rust crate
// (github.com/r12f/divoom, MIT), which documents the same official
// doc.divoom-gz.com page as its source.
//
// A phone-app-internal alternative, Channel/StoreClockGetClassify +
// Channel/StoreClockGetList (per HttpCommand.java + WifiChannelModel.java in
// the decompiled APK), was tried first and abandoned: it returns RC=12
// (HTTP_REQUEST_EMPTY) against the real server for a reason the decompiled
// source can't confirm (BaseParams._postSync, the method that builds the
// actual POST, is a JADX "not decompiled" stub; OkHttpUtils.postSyncInternal
// — which _postSync calls into — IS fully decompiled and confirms no hidden
// headers/signing beyond `Connection: close`, so the gap is specifically in
// that endpoint's expected body/account state, not the transport). Not worth
// chasing further now that a confirmed-working public alternative exists.
//
// Applying a selected ClockId to a device: `divoom_lib.display.show_clock
// (clock=clock_id)` already routes large ids through `lan.set_clock()`
// (`Channel/SetClockSelectId` posted directly to the device's own LAN IP)
// when the device has LAN connectivity — no new device-apply plumbing
// needed on the Rust side either (the daemon's `display.show_clock` device
// call already exists).

// ── AidSleep cloud sound library (natural sounds / white noise / music) ────
//
// Request shape confirmed from the decompiled APK 2026-07-14 (docs/cloud_api/
// tomato_sleep_alarm.md), filtered by `Type` (0=Natural Sound, 1=White
// Noise, 2=Music). Playback needs no cloud call at all — it's a BLE/SPP
// JSON command straight to the device (Python side: `divoom_lib.tools.
// aid_sleep.AidSleep.play`); there is no Rust-daemon equivalent to add here
// since the daemon doesn't own a JSON-over-BLE send path for this command
// family yet.
//
// FIXED (2026-07-14, full writeup in divoom_lib/cloud.py): RC=3 ("request
// data is incomplete") on every request-shape hypothesis was a red herring —
// the real cause was zero devices bound server-side (AidSleep is
// device-scoped, unlike account-scoped Playlist/GetMyList). Fix:
// `cloud::ensure_virtual_device` registers one via `BlueDevice/NewDevice`
// (confirmed live: RC=3 -> RC=0, real sleep-sound catalog).

async fn get_aid_sleep_list(
    cmd: &str,
    sleep_type: i64,
    limit: i64,
    page: i64,
) -> Result<Value, String> {
    let mut creds = get_credentials(false).await?;
    let (device_id, device_pw) = crate::cloud::ensure_virtual_device().await?;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let start = (page - 1) * limit + 1;
    let end = page * limit;
    let make_request = |creds: &DivoomCredentials| -> Value {
        let mut body = json!({
            "Command": cmd,
            "Token": creds.token,
            "UserId": creds.user_id,
            "DeviceId": device_id,
            "Type": sleep_type,
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

    let url = format!("{}/{}", BASE_URL, cmd);
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
        return Err(format!("{cmd} failed (RC={rc}): {msg}"));
    }
    Ok(data
        .get("SleepList")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}

/// Browse Divoom's full cloud AidSleep catalog. `sleep_type`: 0=Natural
/// Sound, 1=White Noise, 2=Music.
pub async fn fetch_aid_sleep_list(sleep_type: i64, limit: i64, page: i64) -> Result<Value, String> {
    get_aid_sleep_list("AidSleep/GetAllList", sleep_type, limit, page).await
}

/// Same shape as `fetch_aid_sleep_list`, scoped to the user's own
/// saved/added tracks.
pub async fn fetch_my_aid_sleep_list(
    sleep_type: i64,
    limit: i64,
    page: i64,
) -> Result<Value, String> {
    get_aid_sleep_list("AidSleep/GetMyList", sleep_type, limit, page).await
}

/// Fetch the clock-face store's category names (`Channel/GetDialType`).
pub async fn get_dial_types() -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let url = format!("{}/Channel/GetDialType", BASE_URL);
    let resp = client
        .post(&url)
        .json(&json!({}))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let data: Value = resp.json().await.map_err(|e| e.to_string())?;
    let rc = data
        .get("ReturnCode")
        .and_then(|v| v.as_i64())
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
pub async fn get_dial_list(dial_type: &str, page: i64) -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let url = format!("{}/Channel/GetDialList", BASE_URL);
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
        .and_then(|v| v.as_i64())
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
pub async fn list_clock_faces(dial_type: Option<String>, page: i64) -> Result<Value, String> {
    let dial_type = match dial_type {
        Some(t) => t,
        None => {
            let types = get_dial_types().await?;
            match types
                .as_array()
                .and_then(|a| a.first())
                .and_then(|v| v.as_str())
            {
                Some(first) => first.to_string(),
                None => return Ok(Value::Array(vec![])),
            }
        }
    };
    get_dial_list(&dial_type, page).await
}

// Playlist endpoints moved to `cloud_playlist.rs` to stay under the file cap.
pub use crate::cloud_playlist::{get_my_playlists, get_playlist_images};
