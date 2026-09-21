//! Top-level daemon cloud commands (gallery + credentials).
//!
//! Split out of `daemon.rs` to keep it under the 500-line house limit. These
//! don't touch the device — they call `crate::cloud` / `crate::cloud_store`
//! directly.

use serde_json::{json, Value};

use crate::protocol::{err_reply, Request};

/// Handle a cloud command. The caller routes only the cloud command names here.
pub async fn handle(command: &str, req: &Request) -> Value {
    match command {
        "fetch_gallery" => fetch_gallery(req).await,

        "save_credentials" => save_credentials(req).await,

        "get_credentials" => get_credentials(req).await,

        "get_cached_credentials" => get_cached_credentials(),

        "get_category_file_list" => get_category_file_list(req).await,

        "store_clock_faces" => store_clock_faces(req).await,

        "get_dial_types" => get_dial_types().await,

        "get_dial_list" => get_dial_list(req).await,

        "list_clock_faces" => list_clock_faces(req).await,

        "search_weather_city" => search_weather_city(req).await,

        "get_aid_sleep_list" | "get_my_aid_sleep_list" => get_aid_sleep_list(command, req).await,

        "get_my_playlists" => get_my_playlists(req).await,

        "get_playlist_images" => get_playlist_images(req).await,

        "get_photo_albums" => get_photo_albums().await,

        other => err_reply(&format!("not a cloud command: {other}")),
    }
}
async fn fetch_gallery(req: &Request) -> Value {
    let Some(classify) = req.args.get("classify").and_then(serde_json::Value::as_i64) else {
        return err_reply("fetch_gallery requires 'classify'");
    };
    let limit = req
        .args
        .get("limit")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(30);
    let file_sort = req
        .args
        .get("file_sort")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    let file_size = req
        .args
        .get("file_size")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(127);
    match crate::cloud::fetch_gallery(classify, limit, file_sort, file_size).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn save_credentials(req: &Request) -> Value {
    let email = req.args.get("email").and_then(|v| v.as_str()).unwrap_or("");
    let password = req
        .args
        .get("password")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if email.is_empty() {
        return err_reply("save_credentials requires 'email'");
    }
    // An empty password means "keep the stored one" (see
    // cloud_store::save_config). Requiring one here made the daemon
    // unable to express an email-only save, which is the common case:
    // the settings form never re-populates the password field.
    //
    // And only FORCE a re-login when a new password was actually
    // supplied. Force-refreshing without one falls back to a guest
    // token, which is how the account silently downgraded before.
    let force = !password.is_empty();
    match crate::cloud_store::save_config(email, password) {
        Ok(()) => match crate::cloud::get_credentials(force).await {
            // R72 P1.1: return the FULL credential, same shape as
            // `get_credentials`. It used to answer with email +
            // user_id only, so a client building a credential value
            // from this reply got token=0 -- i.e. "invalid" -- on a
            // SUCCESSFUL save. Three commands returning three shapes of
            // one value is how a caller ends up special-casing which
            // one it happened to call.
            Ok(creds) => json!({
                "success": true,
                "token": creds.token,
                "user_id": creds.user_id,
                "email": creds.email,
                "utc": creds.utc,
                "password_store": crate::secret_store::label(),
            }),
            Err(e) => err_reply(&format!("saved, but login failed: {e}")),
        },
        Err(e) => err_reply(&e),
    }
}

async fn get_credentials(req: &Request) -> Value {
    let force = req
        .args
        .get("force_refresh")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false);
    match crate::cloud::get_credentials(force).await {
        Ok(creds) => json!({
            "success": true,
            "token": creds.token,
            "user_id": creds.user_id,
            "email": creds.email,
            "utc": creds.utc,
            "password_store": crate::secret_store::label(),
        }),
        Err(e) => err_reply(&e),
    }
}

fn get_cached_credentials() -> Value {
    match crate::cloud::get_cached_credentials() {
        Some(creds) => json!({
            "success": true,
            "credentials": {
                "token": creds.token,
                "user_id": creds.user_id,
                "email": creds.email,
                "utc": creds.utc,
                "password_store": crate::secret_store::label(),
            }
        }),
        None => json!({ "success": true, "credentials": serde_json::Value::Null }),
    }
}

async fn get_category_file_list(req: &Request) -> Value {
    let classify = req
        .args
        .get("classify")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(crate::cloud::DEFAULT_GALLERY_CLASSIFY);
    let limit = req
        .args
        .get("limit")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(20);
    match crate::cloud::get_category_file_list(classify, limit).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn store_clock_faces(req: &Request) -> Value {
    let limit = req
        .args
        .get("limit")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(50);
    let page = req
        .args
        .get("page")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    match crate::cloud_dials::store_clock_faces(limit, page).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn get_dial_types() -> Value {
    match crate::cloud::get_dial_types().await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn get_dial_list(req: &Request) -> Value {
    let dial_type = match req.args.get("dial_type").and_then(|v| v.as_str()) {
        Some(t) => t.to_string(),
        None => return err_reply("get_dial_list requires 'dial_type'"),
    };
    let page = req
        .args
        .get("page")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    match crate::cloud::get_dial_list(&dial_type, page).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn list_clock_faces(req: &Request) -> Value {
    let dial_type = req
        .args
        .get("dial_type")
        .and_then(|v| v.as_str())
        .map(std::string::ToString::to_string);
    let page = req
        .args
        .get("page")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    match crate::cloud::list_clock_faces(dial_type, page).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn search_weather_city(req: &Request) -> Value {
    let keyword = req
        .args
        .get("keyword")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match crate::cloud::search_weather_city(keyword).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn get_aid_sleep_list(command: &str, req: &Request) -> Value {
    let Some(sleep_type) = req
        .args
        .get("sleep_type")
        .and_then(serde_json::Value::as_i64)
    else {
        return err_reply(&format!("{command} requires 'sleep_type'"));
    };
    let limit = req
        .args
        .get("limit")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(30);
    let page = req
        .args
        .get("page")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    let result = if command == "get_aid_sleep_list" {
        crate::cloud::fetch_aid_sleep_list(sleep_type, limit, page).await
    } else {
        crate::cloud::fetch_my_aid_sleep_list(sleep_type, limit, page).await
    };
    match result {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn get_my_playlists(req: &Request) -> Value {
    let limit = req
        .args
        .get("limit")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(30);
    let page = req
        .args
        .get("page")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    match crate::cloud::get_my_playlists(limit, page).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn get_playlist_images(req: &Request) -> Value {
    let Some(play_id) = req.args.get("play_id").and_then(serde_json::Value::as_i64) else {
        return err_reply("get_playlist_images requires 'play_id'");
    };
    let limit = req
        .args
        .get("limit")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(30);
    let page = req
        .args
        .get("page")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(1);
    match crate::cloud::get_playlist_images(play_id, limit, page).await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}

async fn get_photo_albums() -> Value {
    match crate::cloud::get_photo_albums().await {
        Ok(res) => json!({ "success": true, "result": res }),
        Err(e) => err_reply(&e),
    }
}
