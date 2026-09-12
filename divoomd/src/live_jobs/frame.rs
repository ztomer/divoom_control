//! One live-widget frame: bound to the link it was queued on, fenced by the
//! job's `alive` flag, and announced on the bus with its pixels once it lands.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use serde_json::json;

use super::push_rgb_to_device;
use crate::daemon::Daemon;

/// Send one live-widget frame to `mac`, or drop it.
///
/// The frame is queued on the LINK the panel has right now and carries the
/// job's `alive` flag. When its turn comes it re-checks both: a job stopped
/// in the meantime, or a link retired by a reconnect, means the frame is
/// dropped rather than painted over whatever the user asked for since. This
/// is the fence that makes `live_job_stop` and `disconnect` mean "nothing
/// more lands", which the old queue-by-mac closure could not promise.
///
/// Returns whether the frame reached the transport.
pub(super) struct LiveFrame {
    pub rgb: Vec<u8>,
    pub w: i32,
    pub h: i32,
    pub time_ms: u16,
}

pub(super) async fn push_live_frame(
    daemon: &Arc<Daemon>,
    mac: &str,
    kind: &str,
    alive: &Arc<AtomicBool>,
    frame: LiveFrame,
) -> bool {
    let LiveFrame { rgb, w, h, time_ms } = frame;
    let Some(device) = daemon.fleet.get(mac).await else {
        return false;
    };
    let Some(link) = device.link().await else {
        return false;
    };
    let d_weak = Arc::downgrade(daemon);
    let alive = alive.clone();
    let link_in = link.clone();
    let preview = frame_preview_data_url(&rgb, w, h);
    let landed = link
        .run(None, async move {
            if !alive.load(Ordering::SeqCst) || link_in.is_retired() {
                return false;
            }
            let Some(d) = d_weak.upgrade() else {
                return false;
            };
            push_rgb_to_device(&d, &link_in.transport, &rgb, w, h, time_ms)
                .await
                .is_ok()
        })
        .await
        .unwrap_or(false);
    if landed {
        // The panel now shows this frame: say so on the bus, with the
        // pixels, so every preview mirrors the device without polling
        // (2026-09-12: the bench kept the old cover while the device had
        // the new one, because only the Live Widgets tab's poll refreshed
        // it). The activity record keeps it for late subscribers.
        device.set_activity(kind, None, preview.clone()).await;
        let _ = daemon.tx.send(json!({
            "type": "activity",
            "mac": mac,
            "kind": kind,
            "preview": preview,
        }));
    }
    landed
}

/// The frame as a `data:image/png;base64,...` URL, or `None` if the
/// buffer is not `w * h * 3` bytes.
fn frame_preview_data_url(rgb: &[u8], w: i32, h: i32) -> Option<String> {
    use base64::Engine as _;
    let (wu, hu) = (u32::try_from(w).ok()?, u32::try_from(h).ok()?);
    let img = image::RgbImage::from_raw(wu, hu, rgb.to_vec())?;
    let mut png = std::io::Cursor::new(Vec::new());
    img.write_to(&mut png, image::ImageFormat::Png).ok()?;
    Some(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(png.into_inner())
    ))
}
