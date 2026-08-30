//! Art sync, custom-art push/query, and HOT-channel update commands.
//!
//! Ports the Python `owner_art.py`, `divoom_lib/tools/custom_art_push.py`, and
//! `divoom_lib/tools/hot_update.py`. All heavy work (HTTP downloads, AES decoding,
//! image resizing, BLE streaming) runs either in `tokio::task::spawn_blocking` or
//! in async context without blocking the executor. Hot update is fire-and-forget;
//! callers poll `hot_update_progress` for status.
//!
//! Protocol references (APK-verified — see `docs/CUSTOM_CHANNEL_VS_APK.md` and
//! `docs/PLANNING_ROUND36.md`):
//!   - Custom art: B1 (old) / 8C (new) header + data chunks + K0 end signal.
//!   - Hot update:  9B manifest → device drives F7 requests → 9D info → 9E chunks.

use serde_json::{json, Value};
use std::sync::Arc;

use crate::daemon::Daemon;

// R67/C6: HotProgress moved to its own module when art.rs crossed the 500-line
// cap. Re-exported so `crate::art::HotProgress` keeps working for callers.
pub use crate::hot_progress::HotProgress;

// ── constants ─────────────────────────────────────────────────────────────

const CDN_BASE: &str = "https://fin.divoom-gz.com/";

/// 256-byte chunks — matches APK `n().q(256)`.
const CHUNK_SIZE: usize = 256;
/// 40 ms inter-chunk sleep — APK old-mode `q.s().I(true)` sleeps 40 ms.
const INTER_CHUNK_MS: u64 = 40;
/// 15 s HTTP timeout.
const HTTP_TIMEOUT_SECS: u64 = 15;

const SLOTS_PER_PAGE: usize = 12;

/// DeviceType for the hot manifest API keyed by pixel size.
pub(crate) fn device_type_for_size(size: u32) -> u32 {
    match size {
        16 => 1,
        32 => 0,
        64 => 2,
        128 => 3,
        256 => 4,
        _ => 1, // default 16px
    }
}

// ── progress state (shared between hot_update caller and background task) ─

use crate::art_codec::{decode_cloud_magic9, decode_hot_file, decode_magic43};

fn encode_frame(daemon: &Daemon, rgb: &[u8], w: i32, h: i32, time_ms: u16) -> Option<Vec<u8>> {
    #[cfg(feature = "ble")]
    {
        let enc = daemon.encoder()?;
        if w == 32 && h == 32 {
            enc.encode_animation_frame_32(rgb, w, h, time_ms)
        } else {
            enc.encode_animation_frame(rgb, w, h, time_ms)
        }
    }
    #[cfg(not(feature = "ble"))]
    {
        let _ = (daemon, rgb, w, h, time_ms);
        None
    }
}

// ── download + resolve cloud file to 16x16 RGB frame ─────────────────────

async fn download_and_encode_art(daemon: Arc<Daemon>, fid: String) -> Option<Vec<u8>> {
    let url = format!("{CDN_BASE}{fid}");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(HTTP_TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .ok()?;
    let resp = client.get(&url).send().await.ok()?;
    if resp.status() != 200 {
        return None;
    }
    let raw = resp.bytes().await.ok()?;
    if raw.len() < 4 {
        return None;
    }

    // Resolve to 768-byte RGB in a blocking thread (image decoding is CPU-bound).
    let raw_vec = raw.to_vec();
    let daemon_arc = daemon.clone();
    tokio::task::spawn_blocking(move || {
        let rgb = resolve_to_rgb16x16(&raw_vec)?;
        encode_frame(&daemon_arc, &rgb, 16, 16, 500)
    })
    .await
    .ok()
    .flatten()
}

/// Turn any cloud CDN payload into a 768-byte 16x16 RGB buffer.
pub(crate) fn resolve_to_rgb16x16(data: &[u8]) -> Option<Vec<u8>> {
    if data.len() < 4 {
        return None;
    }
    // Already GIF/PNG/JPG — open with image crate, resize to 16x16
    let is_gif = data.starts_with(b"GIF");
    let is_png = data.starts_with(b"\x89PNG");
    let is_jpg = data[0] == 0xFF && data[1] == 0xD8;
    if is_gif || is_png || is_jpg {
        return decode_image_to_rgb(data, 16, 16);
    }
    // Magic 43 — embedded image
    if data[0] == 43 {
        let inner = decode_magic43(data)?;
        return decode_image_to_rgb(&inner, 16, 16);
    }
    // Magic 9 — AES cloud container (16x16 frames)
    if data[0] == 9 {
        let (frames, _) = decode_cloud_magic9(data)?;
        return frames.into_iter().next();
    }
    // 0xAA hot file
    if data[0] == 0xAA {
        let frames = decode_hot_file(data)?;
        return Some(frames.into_iter().next()?.0);
    }
    None
}

/// Decode an image (GIF/PNG/JPG bytes) to a 16x16 RGB flat buffer via the `image` crate.
pub(crate) fn decode_image_to_rgb(data: &[u8], w: u32, h: u32) -> Option<Vec<u8>> {
    use image::imageops::FilterType;
    let img = image::load_from_memory(data).ok()?;
    let resized = img.resize_exact(w, h, FilterType::Nearest);
    Some(resized.to_rgb8().into_raw())
}

// ── custom art protocol helpers (APK LightMakeNewModel.java) ─────────────

fn le16(v: usize) -> [u8; 2] {
    [(v & 0xFF) as u8, ((v >> 8) & 0xFF) as u8]
}

/// Command ids from commands.rs
const CMD_OLD: u8 = 0xB1; // set user gif
const CMD_QUERY: u8 = 0x8E; // app get user define info

#[cfg(feature = "ble")]
async fn push_custom_art_page(
    dev: &crate::daemon::DeviceTransport,
    page: u8,
    frames: &[Vec<u8>],
) -> bool {
    use tokio::time::{sleep, Duration};
    let encoded_blob: Vec<u8> = frames.iter().flat_map(|f| f.iter().copied()).collect();
    let total_len = encoded_blob.len();

    // N2 header (old mode: 0xB1 [0x00, 0x00, page])
    let header = vec![0x00u8, 0x00, page];
    if dev.send_command(CMD_OLD, &header, true).await.is_err() {
        return false;
    }

    // Data chunks
    let mut offset = 0usize;
    while offset < encoded_blob.len() {
        let chunk = &encoded_blob[offset..(offset + CHUNK_SIZE).min(encoded_blob.len())];
        let chunk_size = chunk.len();
        let mut pkt = vec![0x01u8];
        pkt.extend_from_slice(&le16(chunk_size));
        pkt.extend_from_slice(chunk);
        if dev.send_command(CMD_OLD, &pkt, true).await.is_err() {
            return false;
        }
        sleep(Duration::from_millis(INTER_CHUNK_MS)).await;
        offset += CHUNK_SIZE;
    }
    let _ = total_len; // used in new mode only

    // K0 end signal
    dev.send_command(CMD_OLD, &[0x02], true).await.is_ok()
}

// ── public handlers (called from daemon.rs dispatch) ─────────────────────

/// Handle `custom_art_push` command.
pub async fn cmd_custom_art_push(daemon: Arc<Daemon>, args: &Value) -> Value {
    let page = args.get("page").and_then(|v| v.as_u64()).unwrap_or(0) as u8;

    // Build slot_map: {slot_index -> file_id}
    let mut slot_map: Vec<(usize, String)> = Vec::new();
    if let Some(slots_obj) = args.get("slots").and_then(|v| v.as_object()) {
        for (k, fid_val) in slots_obj {
            if let (Ok(idx), Some(fid)) = (k.parse::<usize>(), fid_val.as_str()) {
                if idx < SLOTS_PER_PAGE && !fid.is_empty() {
                    slot_map.push((idx, fid.to_string()));
                }
            }
        }
    } else if let Some(file_ids) = args.get("file_ids").and_then(|v| v.as_array()) {
        let base = args.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        for (i, fid_val) in file_ids.iter().enumerate() {
            if let Some(fid) = fid_val.as_str() {
                if base + i < SLOTS_PER_PAGE {
                    slot_map.push((base + i, fid.to_string()));
                }
            }
        }
    }
    if slot_map.is_empty() {
        return json!({"success": false, "error": "custom_art_push requires 'slots' or 'file_ids'"});
    }

    // Download + encode all files
    let mut frames: Vec<Vec<u8>> = vec![Vec::new(); SLOTS_PER_PAGE];
    for (idx, fid) in &slot_map {
        let encoded = download_and_encode_art(daemon.clone(), fid.clone()).await;
        match encoded {
            Some(e) => frames[*idx] = e,
            None => {
                return json!({"success": false, "error": format!("could not fetch/decode {fid}")})
            }
        }
    }

    // Push to device over BLE
    #[cfg(feature = "ble")]
    {
        let guard = daemon.device.lock().await;
        let dev = match guard.as_ref() {
            Some(d) => d.clone(),
            None => return json!({"success": false, "error": "no device connected"}),
        };
        drop(guard);
        if matches!(
            &*dev,
            crate::daemon::DeviceTransport::Ble(_) | crate::daemon::DeviceTransport::Spp(_)
        ) {
            let ok = push_custom_art_page(&dev, page, &frames).await;
            return json!({
                "success": ok,
                "files_pushed": slot_map.len(),
                "device_confirmed": false,  // ACK != device-confirmed (HW-verified)
            });
        }
    }
    json!({"success": false, "error": "custom_art_push requires BLE/SPP transport"})
}

/// Handle `custom_art_query_page` command.
pub async fn cmd_custom_art_query_page(daemon: Arc<Daemon>, args: &Value) -> Value {
    let page = args.get("page").and_then(|v| v.as_u64()).unwrap_or(0) as u8;
    #[cfg(feature = "ble")]
    {
        let guard = daemon.device.lock().await;
        let dev = match guard.as_ref() {
            Some(d) => d.clone(),
            None => return json!({"success": false, "error": "no device connected"}),
        };
        drop(guard);
        if matches!(
            &*dev,
            crate::daemon::DeviceTransport::Ble(_) | crate::daemon::DeviceTransport::Spp(_)
        ) {
            let resp = dev
                .send_command_and_wait(CMD_QUERY, &[page], std::time::Duration::from_secs(4))
                .await;
            match resp {
                Some(data) if data.len() >= 8 => {
                    let rtype = data[0];
                    if rtype == 2 {
                        return json!({"success": true, "ids": []});
                    }
                    if rtype == 1 {
                        let item_count = u16::from_le_bytes([data[6], data[7]]) as usize;
                        let mut ids = Vec::new();
                        let mut pos = 8;
                        for _ in 0..item_count {
                            if pos + 4 > data.len() {
                                break;
                            }
                            let fid =
                                u32::from_le_bytes(data[pos..pos + 4].try_into().unwrap_or([0; 4]));
                            ids.push(fid);
                            pos += 4;
                        }
                        return json!({"success": true, "ids": ids});
                    }
                    return json!({"success": false, "error": "unexpected response type"});
                }
                _ => {
                    return json!({"success": false, "ids": [], "error": "no response (device timed out)"})
                }
            }
        }
    }
    json!({"success": false, "error": "custom_art_query_page requires BLE transport"})
}

/// Handle `hot_update` command — starts a background task, returns immediately.
pub async fn cmd_hot_update(
    daemon: Arc<Daemon>,
    args: &Value,
    progress: Arc<HotProgress>,
) -> Value {
    let device_size = args
        .get("device_size")
        .and_then(|v| v.as_u64())
        .unwrap_or(16) as u32;
    let show_after = args.get("show").and_then(|v| v.as_bool()).unwrap_or(true);
    // R53: the GUI passes the device address it displays; we stamp the outcome
    // under it so "Last checked <when>" is dated and daemon-owned.
    let address = args
        .get("address")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    if !progress.try_begin() {
        return json!({"success": false, "error": "hot update already in progress"});
    }

    let daemon_arc = daemon.clone();
    let progress_arc = progress.clone();
    tokio::spawn(async move {
        let result = crate::art_hot::run_hot_update(
            daemon_arc.clone(),
            device_size,
            show_after,
            progress_arc.clone(),
        )
        .await;
        match result {
            Ok(summary) => {
                // Stamp the per-device last-checked state before publishing done.
                if let Err(e) = crate::hot_state::record_check(&address, &summary) {
                    eprintln!("[ Wrn ] hot_state record_check failed: {}", e);
                }
                progress_arc.set(json!({"phase": "done", "result": summary}));
            }
            Err(e) => progress_arc.set(json!({"phase": "error", "error": e})),
        }
    });

    json!({"success": true, "started": true})
}

/// Handle `hot_update_progress` command.
///
/// R67: this returned the bare progress object, with NO `success` key — the
/// only reply in the whole protocol without one. A client that branches on
/// `reply["success"]` (which every other reply supports) got a KeyError or a
/// silent falsy. Measured across every read-only command; this was the sole
/// offender.
pub fn cmd_hot_update_progress(progress: &HotProgress) -> Value {
    let mut out = progress.get();
    if let Some(obj) = out.as_object_mut() {
        obj.insert("success".to_string(), json!(true));
    }
    out
}

// ── hot update session (delegated to art_hot.rs) ─────────────────────────
// run_hot_update lives in art_hot to keep art.rs under 500 LOC.
