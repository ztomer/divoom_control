//! The music live job: cover art from MediaRemote to the device.
//!
//! Split out of `mod.rs` in R67 when that file crossed the house 500-line cap.
//!
//! R67/C2: this used to sweep AppleScript across each player and then guess a
//! cover-art URL from the iTunes Search API — a guess that cannot resolve
//! non-album content and needs a network round trip in order to fail. It now
//! pushes the exact image the player is displaying, via the `nowplaying` crate.

use serde_json::Value;
use std::sync::Weak;
use std::time::Duration;

use super::{
    get_device_transport, health, now_playing_track_async, push_rgb_to_device, report_health,
};
use crate::daemon::Daemon;

pub(super) async fn run_music(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    const JOB_KIND: &str = "music";
    let size = params.get("size").and_then(|v| v.as_u64()).unwrap_or(16) as u32;

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
        let daemon = match daemon_weak.upgrade() {
            Some(d) => d,
            None => break,
        };
        let connected = get_device_transport(&daemon, &mac).await.is_some();
        report_health(
            &daemon,
            &health,
            &mac,
            JOB_KIND,
            if connected {
                health::JobState::Running
            } else {
                health::JobState::WaitingForDevice
            },
        )
        .await;

        match now_playing_track_async().await {
            Err(e) => {
                report_health(
                    &daemon,
                    &health,
                    &mac,
                    JOB_KIND,
                    health::JobState::Failed(format!("now-playing unavailable: {e}")),
                )
                .await;
            }
            Ok(None) => {}
            Ok(Some(track)) => {
                let identity = track.identity();
                if identity != last_identity {
                    match track.artwork.as_ref() {
                        // Metadata but no cover — common for podcasts and
                        // streams. Say so rather than leaving the previous
                        // track's art on the panel as if it were current.
                        None => {
                            report_health(
                                &daemon,
                                &health,
                                &mac,
                                JOB_KIND,
                                health::JobState::Failed(format!(
                                    "no cover art for {}",
                                    track.display()
                                )),
                            )
                            .await;
                            last_identity = identity;
                        }
                        Some(art) => match crate::image_proc::process_image_bytes(
                            art.bytes.clone(),
                            size,
                            100,
                        ) {
                            Err(e) => {
                                report_health(
                                    &daemon,
                                    &health,
                                    &mac,
                                    JOB_KIND,
                                    health::JobState::Failed(format!(
                                        "could not decode {} cover art ({} bytes): {e}",
                                        art.format.mime(),
                                        art.len()
                                    )),
                                )
                                .await;
                            }
                            Ok(frames) => {
                                if let Some((rgb, w, h_px, t)) = frames.first() {
                                    if get_device_transport(&daemon, &mac).await.is_some() {
                                        let d_weak = daemon_weak.clone();
                                        let mac_clone = mac.clone();
                                        let rgb_vec = rgb.clone();
                                        let (w_val, h_val, t_val) = (*w, *h_px, *t);
                                        let success = daemon
                                            .queue
                                            .run(None, async move {
                                                if let Some(d) = d_weak.upgrade() {
                                                    if let Some(dev_t) =
                                                        get_device_transport(&d, &mac_clone).await
                                                    {
                                                        push_rgb_to_device(
                                                            &d, &dev_t, &rgb_vec, w_val, h_val,
                                                            t_val,
                                                        )
                                                        .await
                                                        .is_ok()
                                                    } else {
                                                        false
                                                    }
                                                } else {
                                                    false
                                                }
                                            })
                                            .await
                                            .unwrap_or(false);
                                        // Advance only on a CONFIRMED push, so a
                                        // failure retries next tick instead of
                                        // being recorded as done.
                                        if success {
                                            last_identity = identity;
                                            report_health(
                                                &daemon,
                                                &health,
                                                &mac,
                                                JOB_KIND,
                                                health::JobState::Running,
                                            )
                                            .await;
                                        }
                                    }
                                }
                            }
                        },
                    }
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
