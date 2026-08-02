//! `sync_artwork` command — Python-daemon parity (`device_owner.sync_artwork` +
//! `media_decoder.resolve_to_gif`). Download a cloud artwork by `file_id`, resolve
//! it to a renderable image, and show it on the connected device via
//! `display.show_image` (which resizes NEAREST to the device size and 0x8B-streams,
//! matching the Python resize-then-show path).
//!
//! PARITY NOTE: Python's `media_decoder.resolve_to_gif` decodes AES cloud
//! containers (magic 9/18/26, with LZO for 18/26) and 0xAA hot files. The native
//! daemon matches this exactly via `media::resolve_to_gif` (see `art_codec.rs`):
//! magic 9 → AES frames, 18/26 → AES+LZO tiles, 0xAA → palette-delta frames, all
//! re-encoded to an animated GIF the device can render; plus GIF/PNG/JPG and
//! magic-43. The only honest-error path is a truly unrecognized container (line
//! 107), which would otherwise stick the device in its loading animation.

use base64::Engine;
use serde_json::{json, Value};

use crate::daemon::Daemon;
use crate::media::resolve_to_gif;
use crate::protocol::{err_reply, Request};

/// Download a cloud artwork by `file_id` from the Divoom CDN (okhttp UA, 15s
/// timeout). Shared by `sync_artwork` (push) and `get_animated_preview` (display).
pub async fn download_cloud_file(file_id: &str) -> Result<Vec<u8>, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .user_agent("okhttp/4.12.0")
        .build()
        .map_err(|e| format!("client build failed: {e}"))?;
    let url = format!("https://fin.divoom-gz.com/{file_id}");
    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("download failed: {e}"))?;
    if resp.status() != 200 {
        return Err(format!("download status {}", resp.status()));
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("read body failed: {e}"))?
        .to_vec();
    if bytes.len() < 4 {
        return Err("downloaded file too small".into());
    }
    Ok(bytes)
}

/// Resolve a downloaded cloud payload to a `data:<mime>;base64,` preview URL
/// (mime sniffed from the resolved bytes' magic). `None` for undecodable payloads.
/// Mirrors Python `gallery_hot_api.get_animated_preview`'s decode + data-url wrap.
pub fn resolve_preview_data_url(raw: &[u8]) -> Option<String> {
    let img = resolve_to_gif(raw)?;
    let mime = if img.starts_with(b"GIF8") {
        "image/gif"
    } else if img.starts_with(&[0xff, 0xd8]) {
        "image/jpeg"
    } else {
        "image/png"
    };
    let b64 = base64::engine::general_purpose::STANDARD.encode(&img);
    Some(format!("data:{mime};base64,{b64}"))
}

/// `get_animated_preview` command — download a gallery/hot file by `file_id`,
/// decode it daemon-side, and return a base64 data-url for the UI to render
/// (parity with the Python GUI's `gallery_hot_api.get_animated_preview`). Only the
/// small data-url crosses the socket; the raw binary never does.
pub async fn get_animated_preview(args: &Value) -> Value {
    let file_id = match args.get("file_id").and_then(|v| v.as_str()) {
        Some(f) if !f.is_empty() => f.to_string(),
        _ => return err_reply("get_animated_preview requires 'file_id'"),
    };
    let bytes = match download_cloud_file(&file_id).await {
        Ok(b) => b,
        Err(e) => return err_reply(&format!("get_animated_preview: {e}")),
    };
    match resolve_preview_data_url(&bytes) {
        Some(url) => json!({"success": true, "file_id": file_id, "preview": url}),
        None => err_reply(&format!(
            "get_animated_preview: unrecognized container magic {}",
            bytes[0]
        )),
    }
}

pub async fn sync_artwork(daemon: &Daemon, args: &Value) -> Value {
    let _ = daemon
        .tx
        .send(json!({"type":"hot_progress","progress":0,"phase":"starting"}));
    let file_id = match args.get("file_id").and_then(|v| v.as_str()) {
        Some(f) if !f.is_empty() => f.to_string(),
        _ => {
            let _ = daemon
                .tx
                .send(json!({"type":"hot_progress","progress":100,"phase":"error"}));
            return err_reply("sync_artwork requires 'file_id'");
        }
    };
    let size = args
        .get("default_size")
        .and_then(|v| v.as_u64())
        .unwrap_or(16);

    let file_bytes = match download_cloud_file(&file_id).await {
        Ok(b) => b,
        Err(e) => {
            let _ = daemon
                .tx
                .send(json!({"type":"hot_progress","progress":100,"phase":"error"}));
            return err_reply(&format!("sync_artwork: {e}"));
        }
    };

    let img = match resolve_to_gif(&file_bytes) {
        Some(b) => b,
        None => {
            let _ = daemon
                .tx
                .send(json!({"type":"hot_progress","progress":100,"phase":"error"}));
            return err_reply(&format!(
                "sync_artwork: unrecognized container magic {} (could not resolve to an image; \
                 never raw-streamed to avoid sticking the device).",
                file_bytes[0]
            ));
        }
    };

    // display.show_image resizes (NEAREST) to `size` and 0x8B-streams. Box the
    // recursive dispatch (sync_artwork is itself reached via dispatch).
    let res = Box::pin(daemon.dispatch(Request {
        command: "device_call".to_string(),
        args: json!({
            "method": "display.show_image",
            "kwargs": {"size": size},
            "blobs": {"0": base64::engine::general_purpose::STANDARD.encode(&img)},
        }),
        token: None,
    }))
    .await;
    let ok = res
        .get("success")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let _ = daemon.tx.send(json!({"type":"hot_progress","progress":100,"phase":if ok {"done"} else {"error"}, "result":{"success":ok}}));
    json!({"success": ok})
}

#[cfg(test)]
mod tests {
    //! Verify the preview decode + data-url wrap offline against the same cloud
    //! fixtures `media.rs` uses — proving `get_animated_preview` produces a valid
    //! image data-url without needing cloud auth or the network.
    use super::*;
    use std::path::PathBuf;

    fn fixture(name: &str) -> Vec<u8> {
        std::fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("tests/cloud_fixtures")
                .join(name),
        )
        .expect("fixture")
    }

    #[test]
    fn magic9_resolves_to_gif_preview_data_url() {
        let url = resolve_preview_data_url(&fixture("magic9.bin")).expect("preview");
        assert!(url.starts_with("data:image/gif;base64,"));
        // Decodes back to a real image (sanity: the base64 body is valid GIF bytes).
        let b64 = url.strip_prefix("data:image/gif;base64,").unwrap();
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .unwrap();
        assert!(bytes.starts_with(b"GIF8"));
    }

    #[test]
    fn magic18_resolves_to_preview() {
        assert!(resolve_preview_data_url(&fixture("magic18.bin")).is_some());
    }

    #[test]
    fn garbage_yields_no_preview() {
        assert!(resolve_preview_data_url(&[1, 2, 3, 4, 5]).is_none());
    }
}
