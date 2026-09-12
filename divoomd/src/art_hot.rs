//! Hot-channel update session: manifest fetch, file download, BLE streaming.
//! Split from art.rs to keep both files under the 500-LOC ground rule.

use crate::wire::WireNarrow as _;
use serde_json::{json, Value};
use std::sync::Arc;

use crate::art::{device_type_for_size, HotProgress};
use crate::daemon::Daemon;

#[cfg(feature = "ble")]
mod session;

const HOT_API: &str = "https://appin.divoom-gz.com/Hot/GetHotFiles32";
const HOT_FILE_BASE: &str = "https://fin.divoom-gz.com/";
// Both describe how bytes are paced ONTO a device. Without `ble` there is no
// transport to pace, and the hot session that reads them is gated out.
#[cfg(feature = "ble")]
const CHUNK_SIZE: usize = 256;
#[cfg(feature = "ble")]
const IDLE_DONE_TIMEOUT_SECS: f64 = 5.0;
const HTTP_TIMEOUT_SECS: u64 = 15;

struct HotFile {
    vendor_id: u32,
    file_id: String,
    version: u32,
    sha1: String,
    body: Vec<u8>,
}

// The framing half of `HotFile`, in its own impl block so ONE gate covers it:
// only the BLE/SPP session turns a body into packets. Gating the methods
// individually is how the first attempt broke the build -- `checksum` was
// gated, `packet` and `packet_count` were not, and they referenced a
// CHUNK_SIZE that had gone with them.
#[cfg(feature = "ble")]
impl HotFile {
    fn checksum(&self) -> u32 {
        self.body.iter().map(|&b| u32::from(b)).sum::<u32>()
    }
    fn packet(&self, idx: usize) -> Vec<u8> {
        let start = idx * CHUNK_SIZE;
        let chunk = if start < self.body.len() {
            &self.body[start..(start + CHUNK_SIZE).min(self.body.len())]
        } else {
            &[]
        };
        let mut p = chunk.to_vec();
        p.resize(CHUNK_SIZE, 0);
        p
    }
    const fn packet_count(&self) -> usize {
        self.body.len().div_ceil(CHUNK_SIZE)
    }
}

/// Read a u32 from a JSON value that may be a NUMBER or a quoted STRING. The hot
/// API returns `VendorId` as a number but `Version` as a string ("1112"), and
/// serde's `as_u64()` yields None for the string form — which silently zeroed
/// every file's version, so the 0x9B manifest advertised newestVersion=0 and the
/// device never matched an offered file (uploads served 0). Mirrors Python's
/// `int(f["Version"])`, which accepts both.
fn json_u32(v: Option<&Value>) -> u32 {
    match v {
        Some(Value::Number(n)) => n.as_u64().unwrap_or(0).dword(),
        Some(Value::String(s)) => s.trim().parse::<u32>().unwrap_or(0),
        _ => 0,
    }
}

/// Pure parse of the hot-API response body into `HotFile` entries (no bodies yet).
/// Split from the HTTP call so it can be unit-tested against the real response
/// shape (string `Version`, numeric `VendorId`).
fn parse_hot_manifest(data: &Value) -> Vec<HotFile> {
    let mut files = Vec::new();
    for vendor in data
        .get("VendorList")
        .and_then(|v| v.as_array())
        .unwrap_or(&vec![])
    {
        let vid = json_u32(vendor.get("VendorId"));
        for f in vendor
            .get("FileList")
            .and_then(|v| v.as_array())
            .unwrap_or(&vec![])
        {
            let file_id = f
                .get("FileId")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let version = json_u32(f.get("Version"));
            let sha1 = f
                .get("Sha1")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            files.push(HotFile {
                vendor_id: vid,
                file_id,
                version,
                sha1,
                body: Vec::new(),
            });
        }
    }
    files
}

/// `hot_manifest {device_size}` — WHAT the hot channel currently holds, without
/// downloading any of it.
///
/// R70 P2.3. The GUI's "Update Hot Channel" preview used to call the Python
/// `divoom_lib.tools.hot_update.fetch_hot_manifest` in its own process, against
/// the same endpoint this file has always used. Two clients of one API, and the
/// GUI's could not see the cache this module keeps.
///
/// Bodies are deliberately NOT fetched: `parse_hot_manifest` leaves them empty
/// and the preview only needs identities. Downloading ~30 files to render a
/// grid of names would make opening a panel as expensive as a real sync.
pub async fn cmd_hot_manifest(args: &Value) -> Value {
    let size = args
        .get("device_size")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(16)
        .dword();
    let device_type = device_type_for_size(size);
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
    {
        Ok(c) => c,
        Err(e) => return crate::protocol::err_reply(&format!("hot_manifest: {e}")),
    };
    match fetch_hot_manifest(&client, device_type).await {
        Ok(files) => {
            let items: Vec<Value> = files
                .iter()
                .map(|f| {
                    serde_json::json!({
                        "file_id": f.file_id,
                        "version": f.version,
                        "vendor_id": f.vendor_id,
                        "sha1": f.sha1,
                    })
                })
                .collect();
            serde_json::json!({
                "success": true,
                "device_type": device_type,
                "result": items,
            })
        }
        Err(e) => crate::protocol::err_reply(&format!("hot_manifest: {e}")),
    }
}

async fn fetch_hot_manifest(
    client: &reqwest::Client,
    device_type: u32,
) -> Result<Vec<HotFile>, String> {
    let body = serde_json::json!({"DeviceType": device_type, "IsTest": false});
    let resp = client
        .post(HOT_API)
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let data: Value = resp.json().await.map_err(|e| e.to_string())?;
    Ok(parse_hot_manifest(&data))
}

async fn download_hot_file(client: &reqwest::Client, f: &mut HotFile) -> bool {
    let url = format!("{HOT_FILE_BASE}{}", f.file_id);
    let Ok(resp) = client.get(&url).send().await else {
        return false;
    };
    let body = match resp.bytes().await {
        Ok(b) => b.to_vec(),
        Err(_) => return false,
    };
    if !f.sha1.is_empty() {
        // verify SHA-1
        let digest = sha1_digest(&body);
        if digest != f.sha1.to_lowercase() {
            return false;
        }
    }
    f.body = body;
    true
}

#[expect(
    clippy::many_single_char_names,
    clippy::tuple_array_conversions,
    reason = "`a`..`e` and `h[0..5]` are RFC 3174's own names for the SHA-1 \
              working variables. Renaming them to something descriptive would \
              make this harder to check against the specification, which is \
              the only way anyone verifies a hash implementation."
)]
fn sha1_digest(data: &[u8]) -> String {
    // Minimal SHA-1 (RFC 3174) — avoids a dep for a 20-byte output.
    let mut h: [u32; 5] = [
        0x6745_2301,
        0xEFCD_AB89,
        0x98BA_DCFE,
        0x1032_5476,
        0xC3D2_E1F0,
    ];
    let bit_len = (data.len() as u64) * 8;
    let mut padded = data.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in padded.as_chunks::<64>().0 {
        let mut w = [0u32; 80];
        for i in 0..16 {
            w[i] = u32::from_be_bytes(chunk[4 * i..4 * i + 4].try_into().unwrap());
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for (i, wi) in w.iter().enumerate() {
            let (f_val, k) = match i {
                0..=19 => ((b & c) | (!b & d), 0x5A82_7999_u32),
                20..=39 => (b ^ c ^ d, 0x6ED9_EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1B_BCDC),
                _ => (b ^ c ^ d, 0xCA62_C1D6),
            };
            let temp = a
                .rotate_left(5)
                .wrapping_add(f_val)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(*wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temp;
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }
    format!(
        "{:08x}{:08x}{:08x}{:08x}{:08x}",
        h[0], h[1], h[2], h[3], h[4]
    )
}

#[cfg(feature = "ble")]
fn pick_file(files: &[HotFile], vendor_id: u32, version: u32) -> Option<&HotFile> {
    let candidates: Vec<_> = files
        .iter()
        .filter(|f| f.vendor_id == vendor_id && !f.body.is_empty())
        .collect();
    if let Some(exact) = candidates.iter().find(|f| f.version == version) {
        return Some(exact);
    }
    candidates
        .iter()
        .filter(|f| f.version >= version)
        .min_by_key(|f| f.version)
        .copied()
}

// ── Manifest + body cache, keyed by device_type (pixel class) ──────────────
// The manifest and every file body depend ONLY on device_type, so syncing N
// same-size devices would otherwise re-hit the CDN N times (fetch the manifest +
// download all 25 bodies per device). Cache the fully-downloaded set per
// device_type for a short TTL and share it — bodies are read-only during the BLE
// session, so sharing across devices is safe. Ports `_load_hot_files` /
// `_MANIFEST_CACHE_TTL` from `divoom_lib/tools/hot_update.py`.
const MANIFEST_CACHE_TTL_SECS: u64 = 300;
type HotCache =
    std::sync::Mutex<std::collections::HashMap<u32, (std::time::Instant, Arc<Vec<HotFile>>)>>;
static MANIFEST_CACHE: std::sync::OnceLock<HotCache> = std::sync::OnceLock::new();
fn manifest_cache() -> &'static HotCache {
    MANIFEST_CACHE.get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new()))
}

/// Drop all cached manifests (test hook / force-refresh).
#[cfg(test)]
fn clear_manifest_cache() {
    manifest_cache().lock().unwrap().clear();
}

/// Return `(files, downloaded_count, from_cache)` for `device_type`, reusing a
/// recent cached download for the same device class so N same-size devices don't
/// each re-fetch from the CDN. On a miss, fetch the manifest + download every
/// body, then cache the fully-downloaded set.
async fn load_hot_files(
    client: &reqwest::Client,
    device_type: u32,
    progress: &HotProgress,
) -> Result<(Arc<Vec<HotFile>>, usize, bool), String> {
    // Cache hit → reuse. The lock is held only for the sync lookup + clone,
    // never across an await (that would serialize concurrent updates / risk a
    // hang), so drop the guard before any network I/O.
    {
        let cache = manifest_cache().lock().unwrap();
        if let Some((t, files)) = cache.get(&device_type) {
            if t.elapsed().as_secs() < MANIFEST_CACHE_TTL_SECS {
                let dl = files.iter().filter(|f| !f.body.is_empty()).count();
                if dl > 0 {
                    return Ok((files.clone(), dl, true));
                }
            }
        }
    }

    // Miss → fetch the manifest + download every body.
    let mut files = fetch_hot_manifest(client, device_type).await?;
    if files.is_empty() {
        return Err("empty hot manifest".into());
    }
    let total = files.len();
    progress.set(&json!({"phase": "downloading", "current": 0, "total": total}));
    let mut ok_dl = 0usize;
    for (i, f) in files.iter_mut().enumerate() {
        if download_hot_file(client, f).await {
            ok_dl += 1;
        }
        progress
            .set(&json!({"phase":"downloading","current":i+1,"total":total,"file_id":&f.file_id}));
    }
    if ok_dl == 0 {
        return Err("no hot files downloadable".into());
    }

    let arc = Arc::new(files);
    manifest_cache()
        .lock()
        .unwrap()
        .insert(device_type, (std::time::Instant::now(), arc.clone()));
    Ok((arc, ok_dl, false))
}

// CONDITIONAL, because the lint it silences only fires WITH `ble`: the drop
// tightening it is about is in the gated session block. An unconditional
// `expect` here is unfulfilled in the no-BLE build, which `-D warnings` rejects
// -- `expect` policing over-declaration is the reason to prefer it, and the
// reason it has to be cfg'd rather than pasted.
#[cfg_attr(
    not(feature = "ble"),
    expect(
        unused_variables,
        reason = "daemon, show_after and the download count are consumed by the ble-gated hot session; without a transport the function still fetches and decodes, then reports that there is nothing to push"
    )
)]
pub(crate) async fn run_hot_update(
    daemon: Arc<Daemon>,
    device_size: u32,
    show_after: bool,
    progress: Arc<HotProgress>,
) -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(HTTP_TIMEOUT_SECS))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| e.to_string())?;

    // 1+2. Manifest + bodies, cached per device_type so N same-size devices
    // don't each re-hit the CDN (load_hot_files emits the "downloading" progress
    // on a miss; a hit returns instantly).
    progress.set(&json!({"phase": "fetching_manifest"}));
    let device_type = device_type_for_size(device_size);
    let (files, ok_dl, from_cache) = load_hot_files(&client, device_type, &progress).await?;
    if from_cache {
        // Nothing was re-fetched — jump the download bar to full so the UI moves
        // straight to the upload phase instead of sitting at "fetching".
        let n = files.len();
        progress.set(&json!({"phase": "downloading", "current": n, "total": n, "cached": true}));
    }

    // 3. BLE session
    #[cfg(feature = "ble")]
    {
        // Hold the device lock for the WHOLE session: it is device-driven (0xF7/
        // 0x9D/0x9E) and reads the shared notify channel. A concurrent `device_call`
        // grabs this same lock and calls `send_command_and_wait`, which DRAINS that
        // channel (ble.rs) — that would silently steal an in-flight upload's ack/
        // request frames and truncate the transfer. Serializing here makes any
        // concurrent device command wait instead. (Download above ran lock-free —
        // it is pure HTTP; only the BLE exchange needs exclusivity. get_status /
        // hot_update_progress are lock-free so the progress UI is unaffected.)
        //
        // 2026-09-12: "the device lock" is now the panel's ONE queue. Holding
        // its permit is what actually serializes against live-widget frames
        // and GUI device_calls (which ride the same queue); the old
        // `daemon.device` mutex serialized against nothing that mattered.
        // The live widget on this panel is retired first, or it would paint
        // over the hot channel the moment the permit is released.
        let link = daemon
            .resolve_target_link(None)
            .await
            .map_err(|_| "no device connected".to_string())?;
        if let Some(id) = daemon.fleet.current_id().await {
            daemon.live_jobs.stop_all_for_device(&daemon, &id).await;
        }
        let _permit = link
            .queue
            .acquire(None)
            .await
            .map_err(|e| format!("hot_update could not take the device: {e}"))?;
        let dev = link.transport.clone();
        if matches!(
            &*dev,
            crate::daemon::DeviceTransport::Ble(_) | crate::daemon::DeviceTransport::Spp(_)
        ) {
            let result = session::run_hot_session(&dev, &files, ok_dl, progress).await?;
            // Parity with the Python daemon (owner_art.show_hot_channel): after a
            // successful push, switch the device to the HOT/cloud channel so it
            // actually shows what we just uploaded. Without this the files land in
            // the rotation but the screen stays on whatever channel it was on.
            if show_after {
                if let Err(e) = dev.send_command(0x45, &[0x02], true).await {
                    return Err(format!("hot channel switch (0x45 [0x02]) failed: {e}"));
                }
            }
            return Ok(result);
        }
    }
    Err("hot_update requires BLE/SPP transport".into())
}

#[cfg(test)]
#[path = "art_hot_tests.rs"]
mod tests;
