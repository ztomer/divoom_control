//! Top-level daemon cloud commands (gallery + credentials). Split out of
//! `daemon.rs` to keep it under the 500-line house limit. These don't touch the
//! device — they call `crate::cloud` / `crate::cloud_store` directly.

use serde_json::{json, Value};

use crate::protocol::{err_reply, Request};

/// Handle a cloud command. The caller routes only the cloud command names here.
pub async fn handle(command: &str, req: &Request) -> Value {
    match command {
        "fetch_gallery" => {
            let classify = match req.args.get("classify").and_then(|v| v.as_i64()) {
                Some(c) => c,
                None => return err_reply("fetch_gallery requires 'classify'"),
            };
            let limit = req.args.get("limit").and_then(|v| v.as_i64()).unwrap_or(30);
            let file_sort = req
                .args
                .get("file_sort")
                .and_then(|v| v.as_i64())
                .unwrap_or(1);
            let file_size = req
                .args
                .get("file_size")
                .and_then(|v| v.as_i64())
                .unwrap_or(127);
            match crate::cloud::fetch_gallery(classify, limit, file_sort, file_size).await {
                Ok(res) => json!({ "success": true, "result": res }),
                Err(e) => err_reply(&e),
            }
        }

        "save_credentials" => {
            let email = req.args.get("email").and_then(|v| v.as_str()).unwrap_or("");
            let password = req
                .args
                .get("password")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if email.is_empty() || password.is_empty() {
                return err_reply("save_credentials requires 'email' and 'password'");
            }
            match crate::cloud_store::save_config(email, password) {
                Ok(()) => match crate::cloud::get_credentials(true).await {
                    Ok(creds) => {
                        json!({ "success": true, "email": creds.email, "user_id": creds.user_id })
                    }
                    Err(e) => err_reply(&format!("saved, but login failed: {e}")),
                },
                Err(e) => err_reply(&e),
            }
        }

        "get_credentials" => {
            let force = req
                .args
                .get("force_refresh")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            match crate::cloud::get_credentials(force).await {
                Ok(creds) => json!({
                    "success": true,
                    "token": creds.token,
                    "user_id": creds.user_id,
                    "email": creds.email,
                    "utc": creds.utc,
                }),
                Err(e) => err_reply(&e),
            }
        }

        "get_cached_credentials" => match crate::cloud::get_cached_credentials() {
            Some(creds) => json!({
                "success": true,
                "credentials": {
                    "token": creds.token,
                    "user_id": creds.user_id,
                    "email": creds.email,
                    "utc": creds.utc,
                }
            }),
            None => json!({ "success": true, "credentials": serde_json::Value::Null }),
        },

        "get_category_file_list" => {
            let classify = req
                .args
                .get("classify")
                .and_then(|v| v.as_i64())
                .unwrap_or(crate::cloud::DEFAULT_GALLERY_CLASSIFY);
            let limit = req.args.get("limit").and_then(|v| v.as_i64()).unwrap_or(20);
            match crate::cloud::get_category_file_list(classify, limit).await {
                Ok(res) => json!({ "success": true, "result": res }),
                Err(e) => err_reply(&e),
            }
        }

        "get_dial_types" => match crate::cloud::get_dial_types().await {
            Ok(res) => json!({ "success": true, "result": res }),
            Err(e) => err_reply(&e),
        },

        "get_dial_list" => {
            let dial_type = match req.args.get("dial_type").and_then(|v| v.as_str()) {
                Some(t) => t.to_string(),
                None => return err_reply("get_dial_list requires 'dial_type'"),
            };
            let page = req.args.get("page").and_then(|v| v.as_i64()).unwrap_or(1);
            match crate::cloud::get_dial_list(&dial_type, page).await {
                Ok(res) => json!({ "success": true, "result": res }),
                Err(e) => err_reply(&e),
            }
        }

        "list_clock_faces" => {
            let dial_type = req
                .args
                .get("dial_type")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let page = req.args.get("page").and_then(|v| v.as_i64()).unwrap_or(1);
            match crate::cloud::list_clock_faces(dial_type, page).await {
                Ok(res) => json!({ "success": true, "result": res }),
                Err(e) => err_reply(&e),
            }
        }

        "search_weather_city" => {
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

        "get_aid_sleep_list" | "get_my_aid_sleep_list" => {
            let sleep_type = match req.args.get("sleep_type").and_then(|v| v.as_i64()) {
                Some(t) => t,
                None => return err_reply(&format!("{command} requires 'sleep_type'")),
            };
            let limit = req.args.get("limit").and_then(|v| v.as_i64()).unwrap_or(30);
            let page = req.args.get("page").and_then(|v| v.as_i64()).unwrap_or(1);
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

        "get_my_playlists" => {
            let limit = req.args.get("limit").and_then(|v| v.as_i64()).unwrap_or(30);
            let page = req.args.get("page").and_then(|v| v.as_i64()).unwrap_or(1);
            match crate::cloud::get_my_playlists(limit, page).await {
                Ok(res) => json!({ "success": true, "result": res }),
                Err(e) => err_reply(&e),
            }
        }

        "get_playlist_images" => {
            let play_id = match req.args.get("play_id").and_then(|v| v.as_i64()) {
                Some(id) => id,
                None => return err_reply("get_playlist_images requires 'play_id'"),
            };
            let limit = req.args.get("limit").and_then(|v| v.as_i64()).unwrap_or(30);
            let page = req.args.get("page").and_then(|v| v.as_i64()).unwrap_or(1);
            match crate::cloud::get_playlist_images(play_id, limit, page).await {
                Ok(res) => json!({ "success": true, "result": res }),
                Err(e) => err_reply(&e),
            }
        }

        "get_photo_albums" => match crate::cloud::get_photo_albums().await {
            Ok(res) => json!({ "success": true, "result": res }),
            Err(e) => err_reply(&e),
        },

        other => err_reply(&format!("not a cloud command: {other}")),
    }
}
