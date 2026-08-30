//! The daemon's NDJSON command dispatcher. Split from daemon.rs to stay
//! under the 500-LOC ground rule.

use crate::daemon::Daemon;
use crate::protocol::{err_reply, Request};
use serde_json::{json, Value};

pub(super) async fn dispatch(daemon: &Daemon, req: Request) -> Value {
    match req.command.as_str() {
        "ping" => json!({"success": true, "pong": true}),

        "get_status" => {
            #[cfg(target_os = "macos")]
            let status = crate::macos_notifications::status_event().await;
            #[cfg(not(target_os = "macos"))]
            let status = json!({
                "state": "idle",
                "counters": {"seen": 0, "routed": 0, "dropped": 0}
            });

            let mut res = json!({
                "success": true,
                "uptime_s": daemon.started.elapsed().as_secs(),
            });
            if let Some(obj) = res.as_object_mut() {
                if let Some(st_obj) = status.as_object() {
                    for (k, v) in st_obj {
                        obj.insert(k.clone(), v.clone());
                    }
                }
            }
            res
        }

        "device_status" => daemon.device_status().await,

        // exclusive mode is fully real (uses the ported queue's acquire_now /
        // release). The token lives in args (the request-level token is auth).
        "exclusive_start" => match req.args.get("token").and_then(|v| v.as_str()) {
            Some(t) => match daemon.queue.acquire_now(t) {
                Ok(()) => json!({"success": true, "token": t}),
                Err(e) => err_reply(&e.to_string()),
            },
            None => err_reply("exclusive_start requires 'token'"),
        },
        "exclusive_end" => match req.args.get("token").and_then(|v| v.as_str()) {
            Some(t) => {
                daemon.queue.release(t);
                json!({"success": true})
            }
            None => err_reply("exclusive_end requires 'token'"),
        },

        // Graceful stop (Python-daemon parity): signal the main loop, which
        // unlinks the socket and exits after letting this reply flush.
        "shutdown" => {
            daemon.shutdown.notify_one();
            json!({"success": true, "shutting_down": true})
        }

        "probe_lan" => crate::daemon_connect::probe_lan(daemon).await,

        "sync_artwork" => crate::sync_artwork::sync_artwork(daemon, &req.args).await,

        "get_animated_preview" => crate::sync_artwork::get_animated_preview(&req.args).await,

        #[cfg(feature = "ble")]
        "scan" => daemon.cmd_scan(&req).await,
        "connect" => daemon.cmd_connect(&req).await,
        "disconnect" => daemon.cmd_disconnect().await,
        "mock_simulate_drop" => crate::daemon_mock::cmd_mock_simulate_drop(daemon, &req).await,
        "device_call" => daemon.cmd_device_call(&req).await,

        "live_job_start" => {
            let self_weak = match daemon.self_weak.get() {
                Some(w) => w.clone(),
                None => return err_reply("Daemon self_weak not initialized"),
            };
            let mac = match req.args.get("mac").and_then(|v| v.as_str()) {
                Some(m) => m.to_string(),
                None => return err_reply("live_job_start requires 'mac'"),
            };
            let kind = match req.args.get("kind").and_then(|v| v.as_str()) {
                Some(k) => k.to_string(),
                None => return err_reply("live_job_start requires 'kind'"),
            };
            let params = req.args.get("params").cloned().unwrap_or(json!({}));
            match self_weak.upgrade() {
                Some(d) => match daemon.live_jobs.start(d, mac, kind, params).await {
                    Ok(()) => json!({"success": true}),
                    Err(e) => err_reply(&e),
                },
                None => err_reply("Daemon was dropped"),
            }
        }

        "live_job_stop" => {
            let mac = match req.args.get("mac").and_then(|v| v.as_str()) {
                Some(m) => m,
                None => return err_reply("live_job_stop requires 'mac'"),
            };
            let kind = match req.args.get("kind").and_then(|v| v.as_str()) {
                Some(k) => k,
                None => return err_reply("live_job_stop requires 'kind'"),
            };
            let stopped = daemon.live_jobs.stop(daemon, mac, kind).await;
            json!({"success": true, "stopped": stopped})
        }

        "live_job_list" => {
            let mac = req.args.get("mac").and_then(|v| v.as_str());
            let list = daemon.live_jobs.list(mac).await;
            json!({"success": true, "jobs": list})
        }

        "live_jobs_stop_for" => {
            let mac_str = req.args.get("mac").and_then(|v| v.as_str());
            let mac_owner = {
                let guard = daemon.device_id.try_lock().ok();
                guard.and_then(|g| g.clone())
            };
            let mac = match mac_str.or(mac_owner.as_deref()) {
                Some(m) => m,
                None => return err_reply("live_jobs_stop_for requires 'mac' or connected device"),
            };
            let count = daemon.live_jobs.stop_all_for_device(daemon, mac).await;
            json!({"success": true, "count": count})
        }

        "set_device_activity" => {
            let mac = match req.args.get("mac").and_then(|v| v.as_str()) {
                Some(m) => m.to_string(),
                None => return err_reply("set_device_activity requires 'mac'"),
            };
            let kind = match req.args.get("kind").and_then(|v| v.as_str()) {
                Some(k) => k.to_string(),
                None => return err_reply("set_device_activity requires 'kind'"),
            };
            let name = req
                .args
                .get("name")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let preview = req
                .args
                .get("preview")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            daemon
                .live_jobs
                .set_device_activity(mac, kind, name, preview)
                .await;
            json!({"success": true})
        }

        "get_device_activity" => daemon.live_jobs.get_device_activity().await,

        // --- art / hot-channel commands ---
        "custom_art_push" => {
            let self_weak = match daemon.self_weak.get() {
                Some(w) => w.clone(),
                None => return err_reply("Daemon self_weak not initialized"),
            };
            let daemon_arc = match self_weak.upgrade() {
                Some(d) => d,
                None => return err_reply("Daemon was dropped"),
            };
            crate::art::cmd_custom_art_push(daemon_arc, &req.args).await
        }

        "custom_art_query_page" => {
            let self_weak = match daemon.self_weak.get() {
                Some(w) => w.clone(),
                None => return err_reply("Daemon self_weak not initialized"),
            };
            let daemon_arc = match self_weak.upgrade() {
                Some(d) => d,
                None => return err_reply("Daemon was dropped"),
            };
            crate::art::cmd_custom_art_query_page(daemon_arc, &req.args).await
        }

        "hot_update" => {
            let self_weak = match daemon.self_weak.get() {
                Some(w) => w.clone(),
                None => return err_reply("Daemon self_weak not initialized"),
            };
            let daemon_arc = match self_weak.upgrade() {
                Some(d) => d,
                None => return err_reply("Daemon was dropped"),
            };
            let progress = daemon.hot_progress.clone();
            crate::art::cmd_hot_update(daemon_arc, &req.args, progress).await
        }

        "hot_update_progress" => crate::art::cmd_hot_update_progress(&daemon.hot_progress),

        // R67/C2: the ONE place "what is playing?" is answered. The GUI used to
        // answer it a second time in Python, which is why the GUI was the
        // process asking for Apple Music access.
        "now_playing" => crate::now_playing::cmd_now_playing(&req.args),

        // Registration is not playback: a paused player keeps the session, so
        // "who is out there" and "who is playing" are separate questions.
        "players" => crate::now_playing::cmd_players(&req.args),

        // One weather reading, shared by the preview card and the device push.
        "weather" => crate::now_playing::cmd_weather(&req.args).await,

        // --- wall command ---
        "wall_configure" => daemon.cmd_wall_configure(&req).await,

        // --- notification service stubs (macOS only, but wired for parity) ---
        "start_notifications" => {
            #[cfg(target_os = "macos")]
            {
                if let Some(w) = daemon.self_weak.get().and_then(|w| w.upgrade()) {
                    crate::macos_notifications::start_monitor(w).await;
                    let mut status = crate::macos_notifications::status_event().await;
                    status["success"] = json!(true);
                    return status;
                }
            }
            json!({
                "success": false,
                "error": "notifications not available on this platform",
                "state": "idle",
                "counters": {"seen": 0, "routed": 0, "dropped": 0},
                "unsupported": true
            })
        }

        "stop_notifications" => {
            #[cfg(target_os = "macos")]
            {
                crate::macos_notifications::stop_monitor().await;
                let mut status = crate::macos_notifications::status_event().await;
                status["success"] = json!(true);
                status
            }
            #[cfg(not(target_os = "macos"))]
            json!({
                "success": true,
                "state": "idle",
                "counters": {"seen": 0, "routed": 0, "dropped": 0}
            })
        }

        "notification_status" => {
            #[cfg(target_os = "macos")]
            {
                crate::macos_notifications::notification_status().await
            }
            #[cfg(not(target_os = "macos"))]
            json!({
                "success": true,
                "state": "idle",
                "counters": {"seen": 0, "routed": 0, "dropped": 0}
            })
        }

        "set_routing" => {
            #[cfg(target_os = "macos")]
            {
                return crate::macos_notifications::set_routing(&req.args).await;
            }
            #[cfg(not(target_os = "macos"))]
            json!({"success": true})
        }

        "fetch_gallery"
        | "save_credentials"
        | "get_credentials"
        | "get_cached_credentials"
        | "get_category_file_list"
        | "get_dial_types"
        | "get_dial_list"
        | "list_clock_faces"
        | "search_weather_city"
        | "get_aid_sleep_list"
        | "get_my_aid_sleep_list"
        | "get_my_playlists"
        | "get_playlist_images"
        | "get_photo_albums" => crate::cloud_cmds::handle(&req.command, &req).await,

        other => err_reply(&format!(
            "command not implemented in the native daemon yet: {other}"
        )),
    }
}
