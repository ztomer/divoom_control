//! Pushing one device's monthly-best art to that device, over BLE.
//!
//! Split out of `monthly_best.rs` to keep both files under the 500-line house
//! limit: this file is the WIRE (fetch, download, show), the other is the
//! DECISION (which devices, how often, and what a failure means).

use base64::Engine;
use serde_json::json;
use std::time::Duration;
use tokio::time::sleep;

use crate::daemon::Daemon;
use crate::monthly_best::DeviceOutcome;
use crate::protocol::Request;
use crate::settings_devices::RegisteredDevice;

/// How many files to fetch per device.
const LIMIT: i64 = 5;
/// The cloud's sort order — the same one the app's gallery uses.
const SORT: i64 = 1;
/// Every art size, not one bitmask.
const FILE_SIZE: i64 = 127;
/// Seconds to wait between two pushes to the same device.
const PUSH_GAP_SECS: u64 = 15;

/// How many files reached the device, and how many did not.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PushCounts {
    /// Files the device showed.
    pub pushed: usize,
    /// Files that did not make it.
    pub failed: usize,
}

/// Fetch the category for one device, write down what came back, and push it.
pub async fn push_to_device(daemon: &Daemon, device: &RegisteredDevice) -> DeviceOutcome {
    let mut outcome = DeviceOutcome {
        address: device.address.clone(),
        classify: device.classify,
        files: 0,
        pushed: 0,
        error: None,
        warnings: Vec::new(),
    };

    println!(
        "divoomd: fetching gallery for {} (classify={})...",
        device.address, device.classify
    );
    let response = match crate::cloud::fetch_gallery(device.classify, LIMIT, SORT, FILE_SIZE).await
    {
        Ok(response) => response,
        Err(e) => {
            outcome.error = Some(format!("could not fetch the gallery: {e}"));
            return outcome;
        }
    };

    let files = crate::hotchannel_fetches::files_from_response(&response);
    outcome.files = files.len();
    if files.is_empty() {
        outcome.error = Some(format!(
            "the gallery (classify={}) came back with no files",
            device.classify
        ));
        return outcome;
    }

    // What came back, with the dates it carries. The owner's question — is
    // "monthly best" a sliding window? — is answered by diffing two of these
    // lines a day apart, not by a belief.
    for (index, file) in files.iter().enumerate() {
        println!(
            "divoomd: gallery[{index}] {} — date={} by={} id={}",
            file.name, file.date, file.user, file.id
        );
    }
    if let Err(e) =
        crate::hotchannel_fetches::record_fetch(device.classify, &device.address, &files)
    {
        eprintln!("divoomd: could not record the fetch snapshot: {e}");
    }

    match sync_files_to_device(daemon, &device.address, &files).await {
        Ok(counts) => {
            outcome.pushed = counts.pushed;
            if counts.failed > 0 {
                if counts.pushed == 0 {
                    // The device was reached and NOTHING could be shown on
                    // it: the push to this device failed.
                    outcome.error = Some(format!(
                        "the device was reached but none of its {} file(s) could be shown",
                        counts.failed
                    ));
                } else {
                    // Some got through: the device was reached and the art
                    // IS on it. The files that did not make it are a
                    // WARNING — a container format the decoder does not
                    // handle is a defect in the decoder, and a run that
                    // rings the owner's phone every day for it teaches them
                    // to ignore the channel.
                    outcome.warnings.push(format!(
                        "{} of {} file(s) could not be shown",
                        counts.failed,
                        counts.pushed + counts.failed
                    ));
                }
            }
        }
        Err(e) => {
            outcome.error = Some(e);
        }
    }
    outcome
}

/// Pull a gallery file's bytes, or say why not and answer `None`.
async fn download(client: &reqwest::Client, file_id: &str, file_name: &str) -> Option<Vec<u8>> {
    let dl_url = format!("https://fin.divoom-gz.com/{file_id}");
    let resp = match client.get(&dl_url).send().await {
        Ok(r) => r,
        Err(e) => {
            eprintln!("divoomd: failed to download {file_name}: {e}");
            return None;
        }
    };
    if resp.status() != 200 {
        eprintln!(
            "divoomd: download of {} failed with status {}",
            file_name,
            resp.status()
        );
        return None;
    }
    match resp.bytes().await {
        Ok(b) => Some(b.to_vec()),
        Err(e) => {
            eprintln!("divoomd: failed to read bytes for {file_name}: {e}");
            None
        }
    }
}

/// Resolve a gallery file to a displayable image and show it.
///
/// `media::resolve_to_gif` handles GIF/PNG/JPG, magic-43, and the cloud/hot
/// containers (magic 9/18/26 AES+LZO, 0xAA) by re-encoding them to an
/// animated GIF the device can render. The only honest-error path is a truly
/// unrecognized container, which would otherwise stick the device in its
/// loading animation.
async fn show(daemon: &Daemon, file_bytes: &[u8], file_name: &str) -> bool {
    let Some(img) = crate::media::resolve_to_gif(file_bytes) else {
        eprintln!(
            "divoomd: {} (magic {}) not decodable in native daemon; skipping (no raw-stream)",
            file_name, file_bytes[0]
        );
        return false;
    };
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
    daemon
        .dispatch(req_show)
        .await
        .get("success")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
}

/// Connect, push every file, disconnect — and count what actually landed.
///
/// A file that could not be downloaded or shown is a FAILED file, not a
/// skipped one: the caller turns a non-zero failure count into a failed run.
async fn sync_files_to_device(
    daemon: &Daemon,
    target: &str,
    files: &[crate::hotchannel_fetches::FetchedFile],
) -> Result<PushCounts, String> {
    // 1. Connect
    let connect_args = target.strip_prefix("LAN:").map_or_else(
        || {
            json!({
                "mac": target,
                "use_ios_le_protocol": true
            })
        },
        |ip| json!({ "lan_ip": ip }),
    );

    let req_connect = Request {
        command: "connect".to_string(),
        args: connect_args,
        token: None,
    };

    let res = daemon.dispatch(req_connect).await;
    if !res
        .get("success")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
    {
        let err = res
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown connection error");
        return Err(format!("Connection to {target} failed: {err}"));
    }

    // 2. Download and stream each file
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let mut counts = PushCounts {
        pushed: 0,
        failed: 0,
    };
    for (idx, file) in files.iter().enumerate() {
        let file_id = file.id.as_str();
        let file_name = file.name.as_str();

        println!(
            "divoomd: downloading item [{}/{}]: {} ({})...",
            idx + 1,
            files.len(),
            file_name,
            file_id
        );
        let Some(file_bytes) = download(&client, file_id, file_name).await else {
            counts.failed += 1;
            continue;
        };

        if file_bytes.len() < 4 {
            counts.failed += 1;
            continue;
        }

        if show(daemon, &file_bytes, file_name).await {
            counts.pushed += 1;
            println!("divoomd: pushed {file_name}");
        } else {
            counts.failed += 1;
            eprintln!("divoomd: failed to push {file_name}");
        }

        if idx < files.len() - 1 {
            sleep(Duration::from_secs(PUSH_GAP_SECS)).await;
        }
    }

    // 3. Disconnect
    let req_disconnect = Request {
        command: "disconnect".to_string(),
        args: json!({}),
        token: None,
    };
    daemon.dispatch(req_disconnect).await;
    println!("divoomd: sync completed for target {target}");

    Ok(counts)
}

/// Pull a GIF out of a magic-43 container.
#[must_use]
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
        Some(gif_data.to_vec())
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_magic_43_container_hands_back_its_gif() {
        // magic byte 43 (0x2b) + text_len (4 bytes LE) + text content + gif_len (4 bytes LE) + GIF89a
        let text_content = b"my metadata text content";
        let gif_content = b"GIF89a_my_awesome_gif_data_here";
        let mut data = vec![43u8, 0, 0, 0, 0, 0];
        data.extend_from_slice(&u32::try_from(text_content.len()).unwrap_or(0).to_le_bytes());
        data.extend_from_slice(text_content);
        data.extend_from_slice(&u32::try_from(gif_content.len()).unwrap_or(0).to_le_bytes());
        data.extend_from_slice(gif_content);

        let extracted = extract_gif_from_magic_43(&data).unwrap();
        assert_eq!(extracted, gif_content);
    }
}
