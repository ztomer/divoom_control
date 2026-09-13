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

/// The clock-face STORE (`Channel/StoreClockGetClassify` + `StoreClockGetList`):
/// the catalog that carries a picture of each face (`ImagePixelId`), unlike
/// the public `GetDialList` which names faces only. Authenticated and
/// device-scoped. 19 faces on 2026-09-13, ids 998..1021, one category.
///
/// The picture is NOT yet renderable: it is a magic-26 (`0x1A`) container
/// `{magic, frames, speed BE, rows 8, cols 8}` whose frame is a plain
/// `u32 BE length` + a `0xAA` record with flag `0x15` -- the native
/// `pixelEncodeBlueHigh` output, not the AES+LZO layout `decode_cloud_magic18_26`
/// handles and not the 16x16 bit-packed `0xAA` layout either (the index
/// block is far too small for 128x128 at any depth; LZO/zlib/lz4 refuse it).
/// Until that encoding is decoded, no client shows these.
///
/// Probed live 2026-09-13: the earlier RC=12 was the missing virtual device
/// (`BlueDevice/NewDevice`), and RC=3 "Request data is incomplete" was
/// `StartNum` 0 -- it counts from 1. The minimal body is Token, `UserId`,
/// `DeviceId`, `DevicePassword`, `StartNum`, `EndNum` (+ `ClassifyId`, `Flag`).
///
/// # Errors
///
/// See the module note on cloud errors.
pub async fn store_clock_faces(limit: i64, page: i64) -> Result<Value, String> {
    let mut creds = super::cloud::get_credentials(false).await?;
    let (device_id, device_pw) = super::cloud::ensure_virtual_device().await?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;
    let start = (page - 1) * limit + 1;
    let end = page * limit;
    let body_for = |creds: &super::cloud::DivoomCredentials, classify: Option<i64>| {
        let mut body = json!({
            "Token": creds.token, "UserId": creds.user_id,
            "DeviceId": device_id, "DevicePassword": device_pw,
            "StartNum": start, "EndNum": end,
        });
        if let Some(c) = classify {
            body["ClassifyId"] = json!(c);
            body["Flag"] = json!(0);
        }
        body
    };
    let post = |path: &'static str, body: Value| {
        let client = client.clone();
        async move {
            let data: Value = client
                .post(format!("{BASE_URL}/Channel/{path}"))
                .json(&body)
                .send()
                .await
                .map_err(|e| e.to_string())?
                .json()
                .await
                .map_err(|e| e.to_string())?;
            let rc = data
                .get("ReturnCode")
                .and_then(serde_json::Value::as_i64)
                .unwrap_or(-1);
            Ok::<(i64, Value), String>((rc, data))
        }
    };
    let (mut rc, mut data) = post("StoreClockGetClassify", body_for(&creds, None)).await?;
    if rc == 9 || rc == 10 || rc == 11 {
        creds = super::cloud::get_credentials(true).await?;
        (rc, data) = post("StoreClockGetClassify", body_for(&creds, None)).await?;
    }
    if rc != 0 {
        return Err(cloud_err("StoreClockGetClassify", rc, &data));
    }
    let mut faces = Vec::new();
    for classify in data
        .get("ClassifyList")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
    {
        let Some(id) = classify.get("ClassifyId").and_then(Value::as_i64) else {
            continue;
        };
        let category = classify
            .get("ClassifyName")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let (rc, list) = post("StoreClockGetList", body_for(&creds, Some(id))).await?;
        if rc != 0 {
            return Err(cloud_err("StoreClockGetList", rc, &list));
        }
        for f in list
            .get("ClockList")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            faces.push(json!({
                "clock_id": f.get("ClockId"),
                "name": f.get("ClockName"),
                "image_file_id": f.get("ImagePixelId"),
                "clock_type": f.get("ClockType"),
                "category": category,
            }));
        }
    }
    Ok(Value::Array(faces))
}

fn cloud_err(path: &str, rc: i64, data: &Value) -> String {
    let msg = data
        .get("ReturnMessage")
        .and_then(|v| v.as_str())
        .unwrap_or("Unknown cloud error");
    format!("Channel/{path} failed (RC={rc}): {msg}")
}
