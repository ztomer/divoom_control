//! Pushing one device's monthly-best art to that device, over BLE.
//!
//! Split out of `monthly_best.rs` to keep both files under the 500-line house
//! limit: this file is the WIRE (fetch, download, show, store), the other is
//! the DECISION (which devices, how often, and what a failure means).
//!
//! # Two things happen to every file, and they are not the same thing
//!
//! * **SHOWN** — the art is streamed to the panel (`0x8B`). That is a
//!   transient display: the panel shows it and the push moves on.
//! * **STORED** — the art is written into the device's OWN gallery (the
//!   custom-art page; see [`crate::gallery_store`]), so the panel KEEPS it.
//!
//! The owner's ruling (2026-10-21): *"art should be stored"*. The push's job
//! is to leave the art on the device, not to flash it past — so a run that
//! only shows the art has not done its job, and a run that claims to have
//! stored what it did not is a lie. The two are counted apart, and the device
//! that stored NOTHING is a failed run.

use base64::Engine;
use serde_json::json;
use std::time::Duration;
use tokio::time::sleep;

use crate::daemon::Daemon;
use crate::gallery_store::{self, ArtItem};
use crate::monthly_best::DeviceOutcome;
use crate::protocol::Request;
use crate::settings_devices::RegisteredDevice;

/// How many files to fetch per device.
const LIMIT: i64 = 5;
/// The cloud's sort order — the same one the app's gallery uses.
const SORT: i64 = 1;
/// Seconds to wait between two pushes to the same device.
const PUSH_GAP_SECS: u64 = 15;

/// What reached the device, and what it kept.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PushCounts {
    /// Files the device SHOWED.
    pub pushed: usize,
    /// Files the device STORED — the art is in its own gallery.
    pub stored: usize,
    /// The files that did not make it, and why each one did not.
    pub failures: Vec<FileFailure>,
    /// What the device said it holds, when it answers the read-back.
    pub readback: Option<String>,
}

/// One file that did not make it to the device, and why.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileFailure {
    /// The gallery file's name, as the cloud calls it.
    pub name: String,
    /// Why it could not be shown or stored.
    pub reason: String,
}

/// The rule the box records, as a rule about the DEVICE.
///
/// A device that was REACHED and STORED NOTHING is a FAILURE of the run: it
/// rings the owner's phone, because the push's job is to leave the art on the
/// device. A device that stored the art and could not show one file only
/// WARNS — and the warning NAMES the file and says WHY, because a run that
/// says "3 of 10 file(s) could not be shown" says less than the run that
/// names them, and a run that quietly drops files is a run that says less
/// than it does.
#[must_use]
pub fn device_verdict(
    stored: usize,
    offered: usize,
    failures: &[FileFailure],
) -> (Option<String>, Vec<String>) {
    if failures.is_empty() {
        return (None, Vec::new());
    }
    if stored == 0 {
        let total = offered.max(stored + failures.len());
        let named = failures
            .iter()
            .map(|f| format!("{} ({})", f.name, f.reason))
            .collect::<Vec<_>>()
            .join("; ");
        return (
            Some(format!(
                "the device was reached but none of its {total} file(s) could be stored: {named}"
            )),
            Vec::new(),
        );
    }
    (
        None,
        failures
            .iter()
            .map(|f| format!("{}: {}", f.name, f.reason))
            .collect(),
    )
}

/// Fetch the category for one device, write down what came back, and push it.
pub async fn push_to_device(daemon: &Daemon, device: &RegisteredDevice) -> DeviceOutcome {
    let mut outcome = DeviceOutcome {
        address: device.address.clone(),
        classify: device.classify,
        files: 0,
        pushed: 0,
        stored: 0,
        readback: None,
        error: None,
        warnings: Vec::new(),
    };

    // The panel is reached FIRST: its size decides which art the gallery may
    // offer it. Pixel art is shown only on a panel of its own size (D14); the
    // push asked the cloud for every size (127) and squeezed 64x64 art onto
    // 16x16 panels.
    let pixels = match crate::monthly_best_link::connect(daemon, &device.address).await {
        Ok(p) => p,
        Err(e) => {
            outcome.error = Some(e);
            return outcome;
        }
    };
    let Some(bit) = crate::art_source::size_bit(pixels) else {
        outcome.error = Some(format!(
            "the cloud has no gallery for a {pixels}x{pixels} panel"
        ));
        crate::monthly_best_link::disconnect(daemon).await;
        return outcome;
    };
    println!(
        "divoomd: fetching gallery for {} (classify={}, {pixels}x{pixels})...",
        device.address, device.classify
    );
    // `fetch_gallery` lists only the items drawn for this one size.
    let response = match crate::cloud::fetch_gallery(device.classify, LIMIT, SORT, bit).await {
        Ok(response) => response,
        Err(e) => {
            outcome.error = Some(format!("could not fetch the gallery: {e}"));
            crate::monthly_best_link::disconnect(daemon).await;
            return outcome;
        }
    };

    let files = crate::hotchannel_fetches::files_from_response(&response);
    outcome.files = files.len();
    if files.is_empty() {
        outcome.error = Some(format!(
            "the gallery (classify={}) came back with no {pixels}x{pixels} files",
            device.classify
        ));
        crate::monthly_best_link::disconnect(daemon).await;
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

    match sync_files_to_device(daemon, &device.address, pixels, &files).await {
        Ok(counts) => {
            outcome.pushed = counts.pushed;
            outcome.stored = counts.stored;
            outcome.readback.clone_from(&counts.readback);
            // The rule, in one place: a device that was reached and stored
            // NOTHING failed; a device that stored the art and could not show
            // one file only warns — and the warning names the file.
            let (error, warnings) = device_verdict(counts.stored, outcome.files, &counts.failures);
            outcome.error = error;
            outcome.warnings = warnings;
        }
        Err(e) => {
            outcome.error = Some(e);
            crate::monthly_best_link::disconnect(daemon).await;
        }
    }
    outcome
}

/// Pull a gallery file's bytes, or say why not.
async fn download(
    client: &reqwest::Client,
    file_id: &str,
    file_name: &str,
) -> Result<Vec<u8>, String> {
    let dl_url = format!("https://fin.divoom-gz.com/{file_id}");
    let resp = match client.get(&dl_url).send().await {
        Ok(r) => r,
        Err(e) => {
            let reason = format!("the download failed: {e}");
            eprintln!("divoomd: failed to download {file_name}: {reason}");
            return Err(reason);
        }
    };
    if resp.status() != 200 {
        let reason = format!("the download failed with status {}", resp.status());
        eprintln!(
            "divoomd: download of {file_name} failed with status {}",
            resp.status()
        );
        return Err(reason);
    }
    match resp.bytes().await {
        Ok(b) => Ok(b.to_vec()),
        Err(e) => {
            let reason = format!("the download's bytes could not be read: {e}");
            eprintln!("divoomd: failed to read bytes for {file_name}: {reason}");
            Err(reason)
        }
    }
}

/// Resolve a gallery file to a displayable image.
///
/// `media::resolve_to_gif` handles GIF/PNG/JPG, magic-43, and the cloud/hot
/// containers (magic 9/18/26 AES+LZO, 0xAA) by re-encoding them to an
/// animated GIF the device can render. The only honest-error path is a truly
/// unrecognized container, which would otherwise stick the device in its
/// loading animation — and that error says WHICH container it was, so the
/// run can name the file rather than count it.
///
/// The SAME GIF is what the panel is shown and what the device is given to
/// keep: resolving once is what makes "the art that was stored is the art
/// that was shown" true rather than likely.
fn resolve(file_bytes: &[u8], file_name: &str) -> Result<Vec<u8>, String> {
    let Some(img) = crate::media::resolve_to_gif(file_bytes) else {
        let reason = crate::media::why_not_resolvable(file_bytes);
        eprintln!("divoomd: {file_name}: {reason}; skipping (no raw-stream)");
        return Err(reason);
    };
    Ok(img)
}

/// Show resolved pixel art on the panel `target` names, at the panel's own
/// size -- `display.show_image` refuses art drawn for another size (D14).
async fn show(daemon: &Daemon, target: &str, img: &[u8], file_name: &str) -> Result<(), String> {
    let req_show = Request {
        command: "device_call".to_string(),
        args: json!({
            "method": "display.show_image",
            "mac": target,
            "kwargs": {"art": "pixel"},
            "blobs": {
                "0": base64::engine::general_purpose::STANDARD.encode(img)
            }
        }),
        token: None,
    };
    let shown = daemon
        .dispatch(req_show)
        .await
        .get("success")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false);
    if shown {
        Ok(())
    } else {
        Err(format!("the device did not take {file_name}"))
    }
}

/// Push every file to the connected panel, disconnect — and count what actually landed.
///
/// Two things are counted, because they are two things: the files the device
/// SHOWED (the `0x8B` stream) and the files it STORED (the art written into
/// its own gallery). A file that could not be downloaded, shown or stored is a
/// FAILED file, not a skipped one: the caller turns "the device stored
/// nothing" into a failed run.
async fn sync_files_to_device(
    daemon: &Daemon,
    target: &str,
    pixels: u32,
    files: &[crate::hotchannel_fetches::FetchedFile],
) -> Result<PushCounts, String> {
    // 2. Download and stream each file
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    let mut counts = PushCounts::default();
    let mut items: Vec<ArtItem> = Vec::new();
    for (idx, file) in files.iter().enumerate() {
        println!(
            "divoomd: downloading item [{}/{}]: {} ({})...",
            idx + 1,
            files.len(),
            file.name,
            file.id
        );
        push_one_file(
            daemon,
            &client,
            (target, pixels),
            file,
            &mut counts,
            &mut items,
        )
        .await;

        if idx < files.len() - 1 {
            sleep(Duration::from_secs(PUSH_GAP_SECS)).await;
        }
    }

    // 3. STORE: leave the art on the device.
    //
    // Showing is not keeping. The art goes into the device's own gallery (the
    // custom-art page — see `gallery_store`), and the run counts what the
    // device took and what it says it holds.
    store_page(daemon, target, &items, &mut counts).await;

    // 4. Disconnect
    let req_disconnect = Request {
        command: "disconnect".to_string(),
        args: json!({}),
        token: None,
    };
    daemon.dispatch(req_disconnect).await;
    println!("divoomd: sync completed for target {target}");

    Ok(counts)
}

/// Download one file, SHOW it, and keep the frames the device will hold.
async fn push_one_file(
    daemon: &Daemon,
    client: &reqwest::Client,
    (target, pixels): (&str, u32),
    file: &crate::hotchannel_fetches::FetchedFile,
    counts: &mut PushCounts,
    items: &mut Vec<ArtItem>,
) {
    let file_name = file.name.as_str();
    let file_bytes = match download(client, file.id.as_str(), file_name).await {
        Ok(bytes) => bytes,
        Err(reason) => {
            counts.failures.push(FileFailure {
                name: file_name.to_string(),
                reason,
            });
            return;
        }
    };

    if file_bytes.len() < 4 {
        counts.failures.push(FileFailure {
            name: file_name.to_string(),
            reason: "the file was too short to be a container".to_string(),
        });
        return;
    }

    let img = match resolve(&file_bytes, file_name) {
        Ok(img) => img,
        Err(reason) => {
            counts.failures.push(FileFailure {
                name: file_name.to_string(),
                reason,
            });
            return;
        }
    };

    match show(daemon, target, &img, file_name).await {
        Ok(()) => {
            counts.pushed += 1;
            println!("divoomd: pushed {file_name}");
        }
        Err(reason) => {
            eprintln!("divoomd: failed to push {file_name}: {reason}");
            counts.failures.push(FileFailure {
                name: file_name.to_string(),
                reason,
            });
        }
    }

    // The frames the device will KEEP: the same art, in the device's own
    // encoding. A file whose frames cannot be made is a file the device
    // cannot hold, and the run says so.
    match gallery_store::frames_for(&img, pixels) {
        Ok(frames) => items.push(ArtItem {
            name: file_name.to_string(),
            frames,
        }),
        Err(reason) => {
            eprintln!("divoomd: failed to store {file_name}: {reason}");
            counts.failures.push(FileFailure {
                name: file_name.to_string(),
                reason,
            });
        }
    }
}

/// Leave the art on the device: the gallery page, and what it says it holds.
async fn store_page(daemon: &Daemon, target: &str, items: &[ArtItem], counts: &mut PushCounts) {
    match gallery_store::store(daemon, target, items).await {
        Ok(store) => {
            counts.stored = store.stored;
            counts.readback.clone_from(&store.readback);
            counts.failures.extend(store.failures);
            if store.stored > 0 {
                println!(
                    "divoomd: stored {} of {} file(s) in the device's own gallery",
                    store.stored,
                    items.len()
                );
            }
            match &store.readback {
                Some(what) => println!("divoomd: the device's own answer — {what}"),
                None => println!(
                    "divoomd: the device did not answer the read-back query, so the store \
                     cannot be confirmed from this side"
                ),
            }
        }
        Err(e) => {
            counts.failures.push(FileFailure {
                name: "the gallery page".to_string(),
                reason: e,
            });
        }
    }
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
