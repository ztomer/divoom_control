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

use crate::wire::WireNarrow as _;
use serde_json::{json, Value};
use std::sync::Arc;

use crate::daemon::Daemon;
use crate::protocol::{err_code, err_with, ok_reply, ErrorCode};

// R67/C6: HotProgress moved to its own module when art.rs crossed the 500-line
// cap. Re-exported so `crate::art::HotProgress` keeps working for callers.
pub use crate::hot_progress::HotProgress;

// ── constants ─────────────────────────────────────────────────────────────

/// 256-byte chunks — matches APK `n().q(256)`.
#[cfg(feature = "ble")]
const CHUNK_SIZE: usize = 256;
/// 40 ms inter-chunk sleep — APK old-mode `q.s().I(true)` sleeps 40 ms.
#[cfg(feature = "ble")]
const INTER_CHUNK_MS: u64 = 40;

const SLOTS_PER_PAGE: usize = 12;

/// `DeviceType` for the hot manifest API keyed by pixel size.
pub(crate) const fn device_type_for_size(size: u32) -> u32 {
    match size {
        32 => 0,
        64 => 2,
        128 => 3,
        256 => 4,
        _ => 1, // default 16px
    }
}

// ── progress state (shared between hot_update caller and background task) ─

// ── download + resolve a cloud file to ONE frame at its own size ───────────

/// Download cloud art and encode it as one custom-art frame for a
/// `panel`x`panel` device.
async fn download_and_encode_art(
    fid: &str,
    panel: u32,
) -> Result<Vec<u8>, crate::art_source::ArtError> {
    let raw = crate::sync_artwork::download_cloud_file(fid).await?;
    tokio::task::spawn_blocking(move || encode_custom_art(&raw, panel))
        .await
        .map_err(|e| format!("decode task: {e}"))?
}

/// One custom-art frame from a cloud payload, for a `panel`x`panel` device.
///
/// The payload is pixel art, so it is used only at its own size: art drawn
/// for another panel is refused, never scaled (D14). This used to resize
/// every payload to 16x16 (`resolve_to_rgb16x16`), whatever it was drawn for
/// and whatever panel it was going to.
///
/// # Errors
///
/// When the payload is no container this daemon reads, the art is not drawn
/// for `panel`, or the frame cannot be encoded.
pub(crate) fn encode_custom_art(
    raw: &[u8],
    panel: u32,
) -> Result<Vec<u8>, crate::art_source::ArtError> {
    let gif =
        crate::media::resolve_to_gif(raw).ok_or_else(|| crate::media::why_not_resolvable(raw))?;
    let frames = crate::image_proc::prepare(gif, crate::art_source::Source::PixelArt, panel, 500)?;
    let (rgb, w, h, _) = frames.first().ok_or("the art has no frames")?;
    Ok(
        crate::image_encode::encode_animation_frame(rgb, *w, *h, 500)
            .map_err(|why| format!("frame {w}x{h}: {why}"))?,
    )
}

// ── custom art protocol helpers (APK LightMakeNewModel.java) ─────────────

/// Command ids from commands.rs. Both are written onto the wire by the
/// BLE/SPP push path only; with `ble` off there is no transport to send them.
#[cfg(feature = "ble")]
const CMD_OLD: u8 = 0xB1; // set user gif

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
        pkt.extend_from_slice(&crate::wire::le16_len(chunk_size));
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
///
/// # Panics
///
/// If the `slot` argument exceeds the platform word size — unreachable on the
/// 64-bit targets this crate ships.
pub async fn cmd_custom_art_push(daemon: Arc<Daemon>, args: &Value) -> Value {
    // Parsed in both configurations because the no-BLE build still validates
    // and answers the request; only the transport that would USE it is absent.
    let page = args
        .get("page")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(0)
        .byte();
    #[cfg(not(feature = "ble"))]
    let _ = page; // no transport in this build; consumed here

    // The panel must be one that can take a page BEFORE anything is stopped
    // or downloaded, so a refusal has no effect (P5.10). It used to stop the
    // panel's live job and fetch every file from the cloud, and only then
    // notice that a LAN or mock panel cannot take the page.
    let target = args
        .get("mac")
        .and_then(Value::as_str)
        .or_else(|| args.get("target_mac").and_then(Value::as_str));
    let device = match daemon.fleet.resolve_target(target).await {
        Ok(d) => d,
        Err(e) => return e.reply(),
    };
    let Some(link) = device.link().await else {
        return err_code(
            ErrorCode::DeviceDisconnected,
            &format!("device '{}' not connected", device.id),
        );
    };
    if !takes_custom_art(&link.transport) {
        return err_code(
            ErrorCode::Unsupported,
            "custom_art_push requires BLE/SPP transport",
        );
    }
    let Some(panel) = device.panel_pixels().await else {
        return err_code(
            ErrorCode::Unsupported,
            "custom_art_push: the panel does not say how big it is, so no pixel art can be matched to it",
        );
    };
    crate::screen_previews::mark_device_rendered(&device, "custom_art_push");

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
        let base = usize::try_from(
            args.get("slot")
                .and_then(serde_json::Value::as_u64)
                .unwrap_or(0),
        )
        .expect("a slot index fits in a usize on 64-bit targets");
        for (i, fid_val) in file_ids.iter().enumerate() {
            if let Some(fid) = fid_val.as_str() {
                if base + i < SLOTS_PER_PAGE {
                    slot_map.push((base + i, fid.to_string()));
                }
            }
        }
    }
    if slot_map.is_empty() {
        return crate::command_args::missing("custom_art_push", "'slots' or 'file_ids'");
    }

    // Fetched and checked BEFORE the panel's job is stopped: art the panel
    // cannot show natively is refused with no effect on it (D14).
    let frames = match encode_page(&slot_map, panel).await {
        Ok(f) => f,
        Err(refusal) => return refusal,
    };

    daemon
        .live_jobs
        .stop_all_for_device(&daemon, &device.id)
        .await;

    // The panel's one queue: a multi-packet page transfer must not be
    // interleaved with a live-widget frame or a GUI device_call, and
    // holding the permit is what guarantees that (2026-09-12).
    let permit = match link.queue.acquire(None).await {
        Ok(p) => p,
        Err(e) => return e.reply(),
    };
    let detail = json!({
        "files_pushed": slot_map.len(),
        "device_confirmed": false,  // ACK != device-confirmed (HW-verified)
    });
    if push_page(&link.transport, page, &frames).await {
        ok_reply(detail)
    } else {
        // Every failure on this path is a write that could not be sent, so
        // the link is gone: the panel must stop reading as connected, and
        // the drop must be reported (P2.8).
        drop(permit);
        daemon
            .link_failed(
                &device.id,
                &link,
                Some("the panel did not take the custom art page"),
            )
            .await;
        err_with(
            ErrorCode::DeviceDisconnected,
            "the panel did not take the custom art page",
            detail,
        )
    }
}

/// Every slot's frame, at the panel's own size: custom art is pixel art, and
/// art drawn for another size is refused, not scaled (D14).
async fn encode_page(slot_map: &[(usize, String)], panel: u32) -> Result<Vec<Vec<u8>>, Value> {
    let mut frames: Vec<Vec<u8>> = vec![Vec::new(); SLOTS_PER_PAGE];
    for (idx, fid) in slot_map {
        frames[*idx] = download_and_encode_art(fid, panel)
            .await
            .map_err(|e| e.reply(&format!("custom_art_push: {fid}"), ErrorCode::Unsupported))?;
    }
    Ok(frames)
}

/// Whether `dev` can take a custom-art page: only a Bluetooth link can, and
/// only in a build with the BLE push path.
const fn takes_custom_art(dev: &crate::daemon::DeviceTransport) -> bool {
    match dev {
        #[cfg(feature = "ble")]
        crate::daemon::DeviceTransport::Ble(_) => true,
        crate::daemon::DeviceTransport::Spp(_) => cfg!(feature = "ble"),
        _ => false,
    }
}

#[cfg(feature = "ble")]
async fn push_page(dev: &crate::daemon::DeviceTransport, page: u8, frames: &[Vec<u8>]) -> bool {
    push_custom_art_page(dev, page, frames).await
}

/// Without `ble` no transport passes [`takes_custom_art`]'s check, so this is
/// never reached; it keeps one body for both builds.
#[cfg(not(feature = "ble"))]
fn push_page(
    _dev: &crate::daemon::DeviceTransport,
    _page: u8,
    _frames: &[Vec<u8>],
) -> impl std::future::Future<Output = bool> + Send {
    std::future::ready(false)
}

/// Handle `hot_update` command — starts a background task, returns immediately.
///
/// The run's verdict is the panel's hot-channel record (U.5,
/// `crate::hot_verdict`): written when it ends, failed or not, under the
/// panel it ran on, with `by` saying which path asked (`button` -- the
/// default -- or `sync_now`). A panel that is not linked is a verdict too: the
/// run was asked for and could not happen, and that replaces whatever the
/// panel's line said before.
pub async fn cmd_hot_update(
    daemon: Arc<Daemon>,
    args: &Value,
    progress: Arc<HotProgress>,
) -> Value {
    let device_size = args
        .get("device_size")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(16)
        .dword();
    let show_after = args
        .get("show")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(true);
    let Some(by) = crate::hot_verdict::RunBy::from_request(args.get("by").and_then(Value::as_str))
    else {
        return err_code(
            ErrorCode::BadRequest,
            "hot_update: 'by' is 'button' or 'sync_now'",
        );
    };
    let named = args
        .get("address")
        .and_then(|v| v.as_str())
        .filter(|a| !a.is_empty());
    // The panel the run is for, resolved NOW: the verdict and every progress
    // event name it.
    let target = match daemon.fleet.resolve_target(named).await {
        Ok(t) => t,
        Err(e) => {
            if let Some(addr) = named {
                let verdict = crate::hot_verdict::Verdict::from_hot_update(
                    by,
                    crate::civil_time::unix_seconds(),
                    &Err(e.message.clone()),
                );
                crate::hot_verdict::record(&daemon, addr, &verdict);
            }
            return e.reply();
        }
    };
    let address = target.id.clone();
    if target.link().await.is_none() {
        let why = format!("device '{address}' not connected");
        let verdict = crate::hot_verdict::Verdict::from_hot_update(
            by,
            crate::civil_time::unix_seconds(),
            &Err(why.clone()),
        );
        crate::hot_verdict::record(&daemon, &address, &verdict);
        return err_code(ErrorCode::DeviceDisconnected, &why);
    }

    if !progress.try_begin(&address) {
        return err_code(ErrorCode::Busy, "hot update already in progress");
    }

    let reply = json!({"success": true, "started": true, "mac": address});
    let daemon_arc = daemon;
    let progress_arc = progress;
    tokio::spawn(async move {
        let result = crate::art_hot::run_hot_update(
            daemon_arc.clone(),
            device_size,
            show_after,
            progress_arc.clone(),
            Some(address.clone()),
        )
        .await;
        // The verdict is recorded BEFORE the terminal phase is published, so a
        // client that re-reads the record on `done`/`error` finds this run.
        let verdict = crate::hot_verdict::Verdict::from_hot_update(
            by,
            crate::civil_time::unix_seconds(),
            &result,
        );
        crate::hot_verdict::record(&daemon_arc, &address, &verdict);
        match result {
            Ok(summary) => progress_arc.set(&json!({"phase": "done", "result": summary})),
            Err(e) => progress_arc.set(&json!({"phase": "error", "error": e})),
        }
    });

    reply
}

/// Handle `hot_update_progress` command.
///
/// R67: this returned the bare progress object, with NO `success` key — the
/// only reply in the whole protocol without one. A client that branches on
/// `reply["success"]` (which every other reply supports) got a `KeyError` or a
/// silent falsy. Measured across every read-only command; this was the sole
/// offender.
#[must_use]
pub fn cmd_hot_update_progress(progress: &HotProgress) -> Value {
    ok_reply(progress.get())
}

// ── hot update session (delegated to art_hot.rs) ─────────────────────────
// run_hot_update lives in art_hot to keep art.rs under 500 LOC.
