//! One live-widget frame: bound to the link it was queued on, fenced by the
//! job's `alive` flag, and announced on the bus with its pixels once it lands.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use serde_json::json;

use super::push_rgb_to_device;
use crate::daemon::Daemon;
use crate::device::lease::SavedFrame;

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

/// Push one live-preview frame to a device.
///
/// The `daemon` parameter stays — it is how the fleet is looked up and how
/// progress is reported — but the `Weak` upgrade that used to sit inside it is
/// gone: that existed only to reach the C encoder through
/// `Daemon::encoder()`, and the encoder is a free function now.
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
    if !alive.load(Ordering::SeqCst) {
        return false;
    }
    // Kept whether or not it lands: when a screen lease ends, this is what
    // the panel goes back to (P4.6). While the lease holds, the job keeps
    // rendering and its frames stop here, so the queue never sees them.
    device.save_job_frame(SavedFrame {
        rgb: rgb.clone(),
        w,
        h,
        time_ms,
    });
    if device.lease().is_some() {
        return false;
    }
    let alive = alive.clone();
    let link_in = link.clone();
    let preview = crate::preview_url::data_url(&[(rgb.clone(), w, h, 0)]);
    let outcome = link
        .run(None, async move {
            if !alive.load(Ordering::SeqCst) || link_in.is_retired() {
                return Ok(());
            }
            push_rgb_to_device(&link_in.transport, &rgb, w, h, time_ms).await
        })
        .await;
    let landed = matches!(outcome, Some(Ok(())));
    if landed {
        device.record_screen(crate::device::screen::Screen::of_url(
            kind,
            preview.clone(),
            w,
            h,
        ));
    }
    // A frame whose command could not be sent means the panel's LINK is
    // gone: the panel must stop reading as connected, and the drop must be
    // reported -- the same two broadcasts a user-initiated call produces
    // (P2.8). A live widget is the most common writer to a panel, so this
    // is usually how a drop is noticed at all.
    if let Some(Err(super::PushFailure::Link(why))) = &outcome {
        daemon.link_failed(mac, Some(why)).await;
    }
    // A record refused means a `disconnect` forgot the panel after the
    // frame landed: no `activity` event for a panel the fleet let go of.
    if landed
        && device
            .set_activity(kind, None, preview.clone())
            .await
            .is_ok()
    {
        // The panel now shows this frame: say so on the bus, with the
        // pixels, so every preview mirrors the device without polling
        // (2026-09-12: the bench kept the old cover while the device had
        // the new one, because only the Live Widgets tab's poll refreshed
        // it). The activity record keeps it for late subscribers.
        let _ = daemon.tx.send(json!({
            "type": "activity",
            "mac": mac,
            "kind": kind,
            "preview": preview,
        }));
    }
    landed
}
