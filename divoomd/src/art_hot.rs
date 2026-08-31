//! Hot-channel update session: manifest fetch, file download, BLE streaming.
//! Split from art.rs to keep both files under the 500-LOC ground rule.

use serde_json::{json, Value};
use std::sync::Arc;

use crate::art::{device_type_for_size, HotProgress};
use crate::daemon::Daemon;

#[cfg(feature = "ble")]
mod session;

const HOT_API: &str = "https://appin.divoom-gz.com/Hot/GetHotFiles32";
const HOT_FILE_BASE: &str = "https://fin.divoom-gz.com/";
const CHUNK_SIZE: usize = 256;
const IDLE_DONE_TIMEOUT_SECS: f64 = 5.0;
const HTTP_TIMEOUT_SECS: u64 = 15;

struct HotFile {
    vendor_id: u32,
    file_id: String,
    version: u32,
    sha1: String,
    body: Vec<u8>,
}

impl HotFile {
    fn checksum(&self) -> u32 {
        self.body.iter().map(|&b| b as u32).sum::<u32>()
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
    fn packet_count(&self) -> usize {
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
        Some(Value::Number(n)) => n.as_u64().unwrap_or(0) as u32,
        Some(Value::String(s)) => s.trim().parse::<u32>().unwrap_or(0),
        _ => 0,
    }
}

/// Pure parse of the hot-API response body into HotFile entries (no bodies yet).
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
        .and_then(|v| v.as_u64())
        .unwrap_or(16) as u32;
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
    let resp = match client.get(&url).send().await {
        Ok(r) => r,
        Err(_) => return false,
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

fn sha1_digest(data: &[u8]) -> String {
    // Minimal SHA-1 (RFC 3174) — avoids a dep for a 20-byte output.
    let mut h: [u32; 5] = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0];
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
                0..=19 => ((b & c) | (!b & d), 0x5A827999u32),
                20..=39 => (b ^ c ^ d, 0x6ED9EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1BBCDC),
                _ => (b ^ c ^ d, 0xCA62C1D6),
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
    progress.set(json!({"phase": "downloading", "current": 0, "total": total}));
    let mut ok_dl = 0usize;
    for (i, f) in files.iter_mut().enumerate() {
        if download_hot_file(client, f).await {
            ok_dl += 1;
        }
        progress
            .set(json!({"phase":"downloading","current":i+1,"total":total,"file_id":&f.file_id}));
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
    progress.set(json!({"phase": "fetching_manifest"}));
    let device_type = device_type_for_size(device_size);
    let (files, ok_dl, from_cache) = load_hot_files(&client, device_type, &progress).await?;
    if from_cache {
        // Nothing was re-fetched — jump the download bar to full so the UI moves
        // straight to the upload phase instead of sitting at "fetching".
        let n = files.len();
        progress.set(json!({"phase": "downloading", "current": n, "total": n, "cached": true}));
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
        let guard = daemon.device.lock().await;
        let dev = match guard.as_ref() {
            Some(d) => d.clone(),
            None => return Err("no device connected".into()),
        };
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
mod tests {
    use super::*;

    #[test]
    fn json_u32_accepts_number_and_string() {
        assert_eq!(json_u32(Some(&json!(1112))), 1112); // numeric (VendorId shape)
        assert_eq!(json_u32(Some(&json!("1112"))), 1112); // quoted string (Version shape)
        assert_eq!(json_u32(Some(&json!(" 1103 "))), 1103); // padded string
        assert_eq!(json_u32(Some(&json!("nope"))), 0);
        assert_eq!(json_u32(None), 0);
    }

    // Regression: the hot API returns `Version` as a STRING ("1112") and
    // `VendorId` as a NUMBER. Parsing Version with as_u64() zeroed every version,
    // so the 0x9B manifest advertised newestVersion=0 and pick_file never matched
    // the device's request — uploads served 0 files. This asserts versions parse.
    #[test]
    fn parse_manifest_reads_string_versions() {
        let data = json!({
            "VendorList": [{
                "VendorId": 40005454,
                "FileList": [
                    {"FileId": "a.bin", "Version": "1103", "Sha1": "aa"},
                    {"FileId": "b.bin", "Version": "1112", "Sha1": "bb"},
                ],
            }],
        });
        let files = parse_hot_manifest(&data);
        assert_eq!(files.len(), 2);
        assert_eq!(files[0].vendor_id, 40005454);
        assert_eq!(
            files[0].version, 1103,
            "string Version must parse, not zero"
        );
        assert_eq!(files[1].version, 1112);

        // With bodies present, the device's request for v1103 must resolve.
        let mut with_bodies = files;
        for f in &mut with_bodies {
            f.body = vec![0u8; 4];
        }
        let picked = pick_file(&with_bodies, 40005454, 1103);
        assert!(picked.is_some(), "pick_file must match a held version");
        assert_eq!(picked.unwrap().version, 1103);
    }

    // A cache hit must reuse the downloaded set (from_cache=true) and NOT touch
    // the network — this is what stops N same-size devices re-downloading.
    #[tokio::test]
    async fn load_hot_files_returns_cached_without_refetch() {
        clear_manifest_cache();
        let dt = 99u32; // synthetic device_type — no real CDN entry
        let cached = Arc::new(vec![HotFile {
            vendor_id: 1,
            file_id: "x.bin".into(),
            version: 5,
            sha1: String::new(),
            body: vec![1, 2, 3, 4],
        }]);
        manifest_cache()
            .lock()
            .unwrap()
            .insert(dt, (std::time::Instant::now(), cached.clone()));

        // reqwest::Client is unused on a hit; if the cache missed this would hit
        // the network for device_type 99 and return an error/empty instead.
        let (got, dl, from_cache) =
            load_hot_files(&reqwest::Client::new(), dt, &HotProgress::default())
                .await
                .expect("cache hit must succeed without network");
        assert!(from_cache, "should report a cache hit");
        assert_eq!(dl, 1);
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].file_id, "x.bin");
        clear_manifest_cache();
    }
}
