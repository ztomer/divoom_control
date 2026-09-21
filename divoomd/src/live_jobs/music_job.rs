//! The music live job: cover art from MediaRemote to the device.
//!
//! Split out of `mod.rs` in R67 when that file crossed the house 500-line cap.
//!
//! R67/C2: this used to sweep AppleScript across each player and then guess a
//! cover-art URL from the iTunes Search API — a guess that cannot resolve
//! non-album content and needs a network round trip in order to fail. It now
//! pushes the exact image the player is displaying, via the `nowplaying` crate.

use crate::wire::WireNarrow as _;
use serde_json::Value;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Weak};
use std::time::Duration;

use super::{
    get_device_transport, health, now_playing_track_async, push_live_frame, report_health,
    LiveFrame,
};
use crate::daemon::Daemon;

pub(super) async fn run_music(
    daemon_weak: Weak<Daemon>,
    mac: String,
    params: Value,
    alive: Arc<AtomicBool>,
) {
    const JOB_KIND: &str = "music";
    let size = params
        .get("size")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(16)
        .dword();

    // Keyed on the track's identity (artist/title/album), which deliberately
    // EXCLUDES artwork bytes so the same song does not re-push every tick.
    let mut last_identity = String::new();

    // R67/C4: a job with no device used to push nothing, say nothing, and
    // sleep its full interval. It now reports its state on every change and
    // re-checks briskly while waiting.
    let health = daemon_weak
        .upgrade()
        .map(|d| health::JobHealth::new("music", &mac, d.tx.clone()));
    let normal_interval = Duration::from_millis(1500);

    loop {
        let Some(daemon) = daemon_weak.upgrade() else {
            break;
        };
        let connected = get_device_transport(&daemon, &mac).await.is_some();
        report_health(
            &daemon,
            health.as_ref(),
            &mac,
            JOB_KIND,
            if connected {
                health::JobState::Running
            } else {
                health::JobState::WaitingForDevice
            },
        )
        .await;

        let report = |state: health::JobState| {
            report_health(&daemon, health.as_ref(), &mac, JOB_KIND, state)
        };
        match verdict(now_playing_track_async().await, &last_identity) {
            Tick::Nothing => {}
            Tick::Fault(reason) => report(health::JobState::Failed(reason)).await,
            Tick::NoCover { identity, reason } => {
                report(health::JobState::Failed(reason)).await;
                last_identity = identity;
            }
            Tick::Cover { identity, track } => {
                match push_cover(&daemon, &mac, &alive, &track, size, connected).await {
                    // Advance only on a CONFIRMED push, so a failure retries
                    // next tick instead of being recorded as done.
                    Ok(true) => {
                        last_identity = identity;
                        report(health::JobState::Running).await;
                    }
                    Ok(false) => {}
                    Err(reason) => report(health::JobState::Failed(reason)).await,
                }
            }
        }

        let nap = if connected {
            normal_interval
        } else {
            health::wait_interval(normal_interval)
        };
        tokio::time::sleep(nap).await;
    }
}

/// What one tick of the job decided about the current track.
enum Tick {
    /// Nothing playing, or the same track as last time.
    Nothing,
    /// A fault to report; the last pushed identity stands.
    Fault(String),
    /// A new track with metadata but no cover: report it, and remember the
    /// identity so it is not reported again every tick.
    NoCover { identity: String, reason: String },
    /// A new track with cover art to push.
    Cover {
        identity: String,
        track: nowplaying::Track,
    },
}

/// The tick's decision, from what now-playing said and what was last pushed.
fn verdict(now: Result<Option<nowplaying::Track>, String>, last_identity: &str) -> Tick {
    let track = match now {
        Err(e) => return Tick::Fault(format!("now-playing unavailable: {e}")),
        Ok(None) => return Tick::Nothing,
        Ok(Some(track)) => track,
    };
    // A PAUSED track is not pushed. MediaRemote keeps reporting a session's
    // track after it is paused, so without this the panel would keep showing
    // cover art for something nobody is listening to -- and would re-push it
    // on every reconnect.
    if !track.is_playing {
        return Tick::Fault(format!("paused: {}", track.display()));
    }
    let identity = track.identity();
    if identity == last_identity {
        return Tick::Nothing;
    }
    if track.artwork.is_none() {
        // Metadata but no cover -- common for podcasts and streams. Say so
        // rather than leaving the previous track's art on the panel as if it
        // were current.
        return Tick::NoCover {
            reason: format!("no cover art for {}", track.display()),
            identity,
        };
    }
    Tick::Cover { identity, track }
}

/// Decode the track's cover to the panel size and push its first frame.
/// `Ok(true)` is a confirmed push; `Ok(false)` is nothing sent (no device,
/// or the push failed and will retry); `Err` is undecodable art.
async fn push_cover(
    daemon: &Arc<Daemon>,
    mac: &str,
    alive: &Arc<AtomicBool>,
    track: &nowplaying::Track,
    size: u32,
    connected: bool,
) -> Result<bool, String> {
    let Some(art) = track.artwork.as_ref() else {
        return Ok(false);
    };
    let frames =
        crate::image_proc::process_image_bytes(art.bytes.clone(), size, 100).map_err(|e| {
            format!(
                "could not decode {} cover art ({} bytes): {e}",
                art.format.mime(),
                art.len()
            )
        })?;
    let Some((rgb, w, h_px, t)) = frames.first() else {
        return Ok(false);
    };
    if !connected {
        return Ok(false);
    }
    Ok(push_live_frame(
        daemon,
        mac,
        "music",
        alive,
        LiveFrame {
            rgb: rgb.clone(),
            w: *w,
            h: *h_px,
            time_ms: *t,
        },
    )
    .await)
}
