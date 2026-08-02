//! Monthly Best sync background service.
//! Ports `divoom_lib/monthly_best_daemon.py`.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::sleep;

use crate::daemon::Daemon;
use crate::protocol::Request;
use base64::Engine;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct HotchannelConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_interval")]
    pub interval: u64,
    #[serde(default = "default_classify")]
    pub classify: i64,
    #[serde(default)]
    pub targets: Vec<String>,
    #[serde(default)]
    pub device_galleries: HashMap<String, Value>,
}

fn default_interval() -> u64 {
    3600
}
fn default_classify() -> i64 {
    18
}

pub fn load_hotchannel_config() -> HotchannelConfig {
    let mut path = match crate::cloud::config_dir() {
        Some(p) => p,
        None => return default_config(),
    };
    path.push("hotchannel.json");
    if !path.exists() {
        return default_config();
    }
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return default_config(),
    };
    let mut cfg: HotchannelConfig = match serde_json::from_str(&content) {
        Ok(c) => c,
        Err(_) => return default_config(),
    };

    // Normalize values
    cfg.interval = cfg.interval.clamp(60, 2592000); // 60s to 30 days
    if cfg.classify <= 0 {
        cfg.classify = 18;
    }
    cfg
}

fn default_config() -> HotchannelConfig {
    HotchannelConfig {
        enabled: false,
        interval: 3600,
        classify: 18,
        targets: Vec::new(),
        device_galleries: HashMap::new(),
    }
}

pub fn extract_gif_from_magic_43(data: &[u8]) -> Option<Vec<u8>> {
    if data.len() < 10 || data[0] != 43 {
        return None;
    }
    let text_len = u32::from_le_bytes(data[6..10].try_into().ok()?) as usize;
    let text_end = 10 + text_len;
    if data.len() < text_end + 4 {
        return None;
    }
    let gif_len = u32::from_le_bytes(data[text_end..text_end + 4].try_into().ok()?) as usize;
    let gif_start = text_end + 4;
    let gif_end = gif_start + gif_len;
    if gif_end > data.len() {
        return None;
    }
    let gif_data = &data[gif_start..gif_end];
    if gif_data.starts_with(b"GIF89a") || gif_data.starts_with(b"GIF87a") {
        return Some(gif_data.to_vec());
    }
    None
}

pub async fn monthly_best_loop_task(daemon: Arc<Daemon>) {
    // Wait a brief moment after startup before starting
    sleep(Duration::from_secs(5)).await;

    loop {
        let config = load_hotchannel_config();
        if !config.enabled {
            sleep(Duration::from_secs(30)).await;
            continue;
        }

        let interval_secs = config.interval;
        println!("[ ==> ] Native Monthly Best Sync loop cycle started.");

        for target in &config.targets {
            let mut classify = config.classify;
            if let Some(c_val) = config.device_galleries.get(target) {
                if let Some(c) = c_val.as_i64() {
                    classify = c;
                }
            }

            println!(
                "[ ==> ] Fetching gallery for target {} (classify={})...",
                target, classify
            );
            // Limit to 5 items to match python daemon default limit
            match crate::cloud::fetch_gallery(classify, 5, 1, 127).await {
                Ok(resp_val) => {
                    let file_list = resp_val.get("FileList").and_then(|v| v.as_array());
                    if let Some(files) = file_list {
                        if !files.is_empty() {
                            println!(
                                "[ Ok  ] Found {} files. Syncing to {}...",
                                files.len(),
                                target
                            );
                            if let Err(e) = sync_files_to_device(&daemon, target, files).await {
                                eprintln!("[ Err ] Failed to sync to {}: {}", target, e);
                            }
                        }
                    }
                }
                Err(e) => {
                    eprintln!("[ Err ] Failed to fetch gallery for {}: {}", target, e);
                }
            }
        }

        println!(
            "[ ==> ] Sleeping for {} seconds until next monthly best cycle...",
            interval_secs
        );
        sleep(Duration::from_secs(interval_secs)).await;
    }
}

async fn sync_files_to_device(
    daemon: &Daemon,
    target: &str,
    files: &[Value],
) -> Result<(), String> {
    // 1. Connect
    let mut connect_args = json!({});
    if let Some(ip) = target.strip_prefix("LAN:") {
        connect_args = json!({
            "lan_ip": ip
        });
    } else {
        connect_args = json!({
            "mac": target,
            "use_ios_le_protocol": true
        });
    }

    let req_connect = Request {
        command: "connect".to_string(),
        args: connect_args,
        token: None,
    };

    let res = daemon.dispatch(req_connect).await;
    if !res
        .get("success")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        let err = res
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown connection error");
        return Err(format!("Connection to {} failed: {}", target, err));
    }

    // 2. Download and stream each file
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    for (idx, item) in files.iter().enumerate() {
        let file_id = match item.get("FileId").and_then(|v| v.as_str()) {
            Some(f) => f,
            None => continue,
        };
        let file_name = item
            .get("FileName")
            .and_then(|v| v.as_str())
            .unwrap_or("unnamed");

        println!(
            "[ ==> ] Downloading item [{}/{}]: {} ({})...",
            idx + 1,
            files.len(),
            file_name,
            file_id
        );
        let dl_url = format!("https://fin.divoom-gz.com/{}", file_id);

        let resp = match client.get(&dl_url).send().await {
            Ok(r) => r,
            Err(e) => {
                eprintln!("[ Wrn ] Failed to download {}: {}", file_name, e);
                continue;
            }
        };

        if resp.status() != 200 {
            eprintln!(
                "[ Wrn ] Download of {} failed with status {}",
                file_name,
                resp.status()
            );
            continue;
        }

        let file_bytes = match resp.bytes().await {
            Ok(b) => b.to_vec(),
            Err(e) => {
                eprintln!("[ Wrn ] Failed to read bytes for {}: {}", file_name, e);
                continue;
            }
        };

        if file_bytes.len() < 4 {
            continue;
        }

        // Resolve to a displayable image and show it. `media::resolve_to_gif`
        // handles GIF/PNG/JPG, magic-43, and the cloud/hot containers (magic 9/18/26
        // AES+LZO, 0xAA) by re-encoding them to an animated GIF the device can
        // render. The only honest-error path is a truly unrecognized container,
        // which would otherwise stick the device in its loading animation.
        let success = match crate::media::resolve_to_gif(&file_bytes) {
            Some(img) => {
                let req_show = Request {
                    command: "device_call".to_string(),
                    args: json!({
                        "method": "display.show_image",
                        "kwargs": {"size": 16},
                        "blobs": {
                            "0": base64::engine::general_purpose::STANDARD.encode(&img)
                        }
                    }),
                    token: None,
                };
                let res_show = daemon.dispatch(req_show).await;
                res_show
                    .get("success")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
            }
            None => {
                eprintln!(
                    "[ Wrn ] {} (magic {}) not decodable in native daemon; skipping (no raw-stream)",
                    file_name, file_bytes[0]
                );
                false
            }
        };

        if success {
            println!("[ Ok  ] Successfully pushed {}", file_name);
        } else {
            eprintln!("[ Err ] Failed to push {}", file_name);
        }

        if idx < files.len() - 1 {
            sleep(Duration::from_secs(15)).await;
        }
    }

    // 3. Disconnect
    let req_disconnect = Request {
        command: "disconnect".to_string(),
        args: json!({}),
        token: None,
    };
    daemon.dispatch(req_disconnect).await;
    println!("[ ==> ] Sync completed for target {}", target);

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_extract_gif_from_magic_43() {
        // magic byte 43 (0x2b) + text_len (4 bytes LE) + text content + gif_len (4 bytes LE) + GIF89a
        let text_content = b"my metadata text content";
        let gif_content = b"GIF89a_my_awesome_gif_data_here";
        let mut data = vec![43u8, 0, 0, 0, 0, 0];
        data.extend_from_slice(&(text_content.len() as u32).to_le_bytes());
        data.extend_from_slice(text_content);
        data.extend_from_slice(&(gif_content.len() as u32).to_le_bytes());
        data.extend_from_slice(gif_content);

        let extracted = extract_gif_from_magic_43(&data).unwrap();
        assert_eq!(extracted, gif_content);
    }

    #[test]
    fn test_load_hotchannel_config() {
        let _lock = crate::cloud::TEST_MUTEX
            .get_or_init(|| tokio::sync::Mutex::new(()))
            .blocking_lock();
        let temp = TempDir::new().unwrap();
        std::env::set_var("HOME", temp.path());

        let conf_dir = temp.path().join(".config").join("divoom-control");
        fs::create_dir_all(&conf_dir).unwrap();

        let hc_json = r#"{"enabled": true, "interval": 120, "classify": 9, "targets": ["AA:BB:CC:DD:EE:FF"]}"#;
        fs::write(conf_dir.join("hotchannel.json"), hc_json).unwrap();

        let cfg = load_hotchannel_config();
        assert!(cfg.enabled);
        assert_eq!(cfg.interval, 120);
        assert_eq!(cfg.classify, 9);
        assert_eq!(cfg.targets, vec!["AA:BB:CC:DD:EE:FF"]);
    }
}
