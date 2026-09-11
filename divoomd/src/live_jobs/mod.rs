use crate::wire::WireNarrow as _;
use serde_json::Value;
use std::sync::{Arc, Weak};
use std::time::Duration;

use crate::daemon::{Daemon, DeviceTransport};

mod coordinator;
pub mod font;
mod health;
/// macOS-only: it reads now-playing through the `nowplaying` crate, which is
/// itself a macOS-only dependency of this crate (MediaRemote does not exist
/// elsewhere). Gating the MODULE rather than sprinkling cfgs inside it keeps
/// the Linux build honest — R67 briefly broke it by leaving the call sites
/// unguarded after the macOS-only helpers were introduced.
#[cfg(target_os = "macos")]
mod music_job;
pub mod render;
pub mod sysmon;

pub use coordinator::LiveJobCoordinator;
pub use health::{JobHealth, JobState};
#[cfg(target_os = "macos")]
use music_job::run_music;

use render::{render_stock, render_sysmon};

/// One call into the now-playing library, isolated so the macOS-only dependency
/// has a single seam and the job body stays readable.
///
/// R67/C2: this replaces `music::get_current_playing_track` +
/// `music::fetch_album_art_url` — an `AppleScript` sweep over each player
/// followed by an iTunes Search URL guessed from the track name. The guess
/// could not resolve non-album content (`YouTube` Music, podcasts, live sets) and
/// needed a network round trip in order to fail. `MediaRemote` returns the exact
/// image the player is displaying, as bytes.
/// Report a job's state on the bus AND into the coordinator's resync store.
///
/// R67: `JobHealth` emits only on transitions, so a UI subscribing after a job
/// starts sees nothing. `live_job_list` answers that, but only if the state is
/// stored — and storing it at each call site separately is how the two would
/// drift. One helper does both halves.
#[expect(
    clippy::ref_option,
    reason = "the caller holds an Option<JobHealth> and reports through it when there is one. Option<&JobHealth> pushes an as_ref() to five call sites"
)]
async fn report_health(
    daemon: &Daemon,
    health: &Option<health::JobHealth>,
    mac: &str,
    kind: &str,
    state: health::JobState,
) {
    let Some(h) = health else { return };
    h.report(state);
    if let Some(snapshot) = h.snapshot() {
        daemon.live_jobs.record_health(mac, kind, snapshot).await;
    }
}

/// Blocking: it spawns `/usr/bin/perl` and waits up to 8s. Callers on the async
/// runtime MUST go through `now_playing_track_async`, or a slow helper stalls
/// every other task on the executor — including the BLE command queue.
#[cfg(target_os = "macos")]
fn now_playing_track() -> Result<Option<nowplaying::Track>, String> {
    nowplaying::current_track()
}

/// The async-safe wrapper: runs the blocking query on the blocking pool.
#[cfg(target_os = "macos")]
async fn now_playing_track_async() -> Result<Option<nowplaying::Track>, String> {
    tokio::task::spawn_blocking(now_playing_track)
        .await
        .map_err(|e| format!("now-playing task failed: {e}"))?
}

// --- Device Helpers ---

async fn push_rgb_to_device(
    daemon: &Daemon,
    dev: &DeviceTransport,
    rgb: &[u8],
    w: i32,
    h: i32,
    time_ms: u16,
) -> Result<(), String> {
    if let DeviceTransport::Lan(_) = dev {
        return Err("LAN image push not supported".into());
    }

    let enc = daemon.encoder().ok_or("encoder not available")?;
    let frame_body = if w == 32 && h == 32 {
        enc.encode_animation_frame_32(rgb, w, h, time_ms)
    } else {
        enc.encode_animation_frame(rgb, w, h, time_ms)
    };
    let blob = frame_body.ok_or("encode failed")?;

    dev.send_command(0x45, &[0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0], false)
        .await
        .map_err(|e| format!("show_design failed: {e}"))?;

    dev.stream_animation_8b(&blob)
        .await
        .map(|_| ())
        .map_err(|e| format!("stream_8b failed: {e}"))
}

async fn get_device_transport(daemon: &Daemon, mac: &str) -> Option<Arc<DeviceTransport>> {
    let dev_opt = daemon.devices.lock().await.get(mac).cloned();
    if let Some(t) = dev_opt {
        return Some(t);
    }
    let cur_id = daemon.device_id.lock().await.clone().unwrap_or_default();
    if cur_id == mac {
        return daemon.device.lock().await.clone();
    }
    None
}

// --- Live Widgets Loops ---

#[expect(
    clippy::cast_possible_wrap,
    reason = "system percentages and byte rates rendered onto a panel, converted for the drawing arithmetic below"
)]
async fn run_sysmon(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    const JOB_KIND: &str = "sysmon";
    let size = params
        .get("size")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(16)
        .dword();
    let mut sys = sysinfo::System::new_all();

    // R67/C4: a job with no device used to push nothing, say nothing, and
    // sleep its full interval. It now reports its state on every change and
    // re-checks briskly while waiting.
    let health = daemon_weak
        .upgrade()
        .map(|d| health::JobHealth::new("sysmon", &mac, d.tx.clone()));
    let normal_interval = Duration::from_secs(5);

    loop {
        let Some(daemon) = daemon_weak.upgrade() else {
            break;
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

        sys.refresh_cpu();
        sys.refresh_memory();

        // Shared with the one-shot `sysmon` request, so the GUI's preview tile
        // and this device frame cannot disagree -- see `live_jobs::sysmon`.
        let s = sysmon::sample(&sys);
        let rgb = render_sysmon(s.cpu, s.mem, s.battery, size);

        if get_device_transport(&daemon, &mac).await.is_some() {
            let d_weak = daemon_weak.clone();
            let mac_clone = mac.clone();
            let _ = daemon
                .queue
                .run(None, async move {
                    if let Some(d) = d_weak.upgrade() {
                        if let Some(dev_t) = get_device_transport(&d, &mac_clone).await {
                            let _ =
                                push_rgb_to_device(&d, &dev_t, &rgb, size as i32, size as i32, 100)
                                    .await;
                        }
                    }
                })
                .await;
        }

        let nap = if connected {
            normal_interval
        } else {
            health::wait_interval(normal_interval)
        };
        tokio::time::sleep(nap).await;
    }
}

#[expect(
    clippy::cast_possible_wrap,
    reason = "a price and a percentage change rendered onto a panel"
)]
async fn run_stocks(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    const JOB_KIND: &str = "stocks";
    let symbol = params
        .get("symbol")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if symbol.is_empty() {
        return;
    }
    let size = params
        .get("size")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(16)
        .dword();
    let client = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        .build()
        .unwrap_or_default();

    // R67/C4: a job with no device used to push nothing, say nothing, and
    // sleep its full interval. It now reports its state on every change and
    // re-checks briskly while waiting.
    let health = daemon_weak
        .upgrade()
        .map(|d| health::JobHealth::new("stocks", &mac, d.tx.clone()));
    let normal_interval = Duration::from_secs(15);

    loop {
        let Some(daemon) = daemon_weak.upgrade() else {
            break;
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

        // ONE quote fetcher, shared with the `render_widget` one-shot
        // (crate::render_widget::fetch_quote). This was inline here; adding a
        // second copy for the preview would have re-created, in Rust, the very
        // split R70 is removing from the GUI.
        if let Ok(quote) = crate::render_widget::fetch_quote(&client, &symbol).await {
            let rgb = render_stock(&symbol, quote.price, quote.change, size);

            if get_device_transport(&daemon, &mac).await.is_some() {
                let d_weak = daemon_weak.clone();
                let mac_clone = mac.clone();
                let _ = daemon
                    .queue
                    .run(None, async move {
                        if let Some(d) = d_weak.upgrade() {
                            if let Some(dev_t) = get_device_transport(&d, &mac_clone).await {
                                let _ = push_rgb_to_device(
                                    &d,
                                    &dev_t,
                                    &rgb,
                                    size as i32,
                                    size as i32,
                                    100,
                                )
                                .await;
                            }
                        }
                    })
                    .await;
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

/// The weather job's device sequence, extracted so a test can watch it.
///
/// It lives apart from `run_weather` because that function fetches from
/// wttr.in, and a test that has to reach the network to check a byte sequence
/// is a test nobody trusts. This is the half worth pinning.
pub(crate) async fn push_weather(
    dev_t: &Arc<DeviceTransport>,
    info: crate::weather::WeatherInfo,
    select_face: bool,
) {
    // The 0x32 that used to open this sequence is GONE (2026-09-07).
    //
    // It was the only 0x32 in the daemon, a bare literal with no test and no
    // note, sending `[01 00 FF FF FF 00]`. The opcode is a DEAD ENTRY on both
    // sides of the port -- `divoom_lib/models/commands.py` and this crate's own
    // `commands.rs` both map "set lightness" to 0x32 and neither map has a
    // caller -- so nothing here had ever verified what it does.
    //
    // What the hardware showed: the clock packet below CYCLES clock ->
    // temperature when sent on its own, and kept cycling when the 0x5F data was
    // sent before it, after it, and with the panel dimmed. Every variable was
    // eliminated except this send, which also dropped screen brightness 80 -> 66
    // on every run while the music job left brightness alone.
    // 0x5F updates the temperature and icon ON the weather face; it does not
    // bring that face forward. Sent AFTER the 0x32 so that whatever that does
    // to the channel, this wins.
    if select_face {
        // A ClockPacket, NOT `channel_switch(Channel::Clock)`. The bare helper
        // is `[channel, 0 x 9]`, which for the clock means active=0 and an RGB
        // of BLACK -- an inactive clock face drawn in black. Sent on hardware
        // 2026-09-07 it turned "still seeing album art" into a blank screen,
        // which is a different bug, not a fix. `switch_channel("clock")` had
        // used the packet builder for exactly this reason; this send did not.
        //
        // `weather: true` is the point of the job: R73 established on hardware
        // that the clock face's extra panels are what put weather on the
        // screen. Selecting the channel alone would show a clock.
        let face = crate::packets::ClockPacket {
            weather: true,
            ..Default::default()
        };
        let _ = dev_t
            .send_command(crate::packets::CMD_SET_LIGHT_MODE, &face.to_bytes(), false)
            .await;
    }

    let packet = crate::packets::WeatherPacket {
        temperature_c: info.temperature_c,
        weather: info.weather,
    };
    let _ = dev_t
        .send_command(
            crate::packets::CMD_SET_TEMP_WEATHER,
            &packet.to_bytes(),
            true,
        )
        .await;
}

async fn run_weather(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    const JOB_KIND: &str = "weather";
    let location = params
        .get("location")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let client = reqwest::Client::new();

    // R67/C4: a job with no device used to push nothing, say nothing, and
    // sleep its full interval. It now reports its state on every change and
    // re-checks briskly while waiting.
    let health = daemon_weak
        .upgrade()
        .map(|d| health::JobHealth::new("weather", &mac, d.tx.clone()));
    let normal_interval = Duration::from_mins(15);

    // Has this job selected the face its data is drawn on?
    //
    // 0x5F updates the temperature and icon ON the weather face; it does not
    // bring that face forward. Every other live widget pushes frames into the
    // channel it selects and is therefore self-sufficient — weather is the only
    // one whose output is owned by a DIFFERENT channel, and it used to assume
    // the device was already showing it. Verified on hardware 2026-09-07: with
    // the panel left in Design by the album-art job, weather reported
    // `{"success": true}` and the operator kept seeing album art.
    //
    // Asserted when the job starts and again whenever it re-acquires the device
    // after a disconnect, but NOT on every 15-minute refresh: re-selecting the
    // channel under someone who deliberately switched away would be the job
    // fighting its user.
    let mut face_selected = false;

    loop {
        let Some(daemon) = daemon_weak.upgrade() else {
            break;
        };
        let connected = get_device_transport(&daemon, &mac).await.is_some();
        if !connected {
            // The next successful push is a fresh acquisition, and the device
            // may well have come back on a different channel.
            face_selected = false;
        }
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

        // R67/C2: the fetch and the WMO mapping used to be inline here, a
        // second copy of divoom_lib/weather_provider.py. They now live in
        // crate::weather, which a parity gate compares against the Python side.
        match crate::weather::fetch(&client, &location).await {
            Err(e) => {
                report_health(
                    &daemon,
                    &health,
                    &mac,
                    JOB_KIND,
                    health::JobState::Failed(e),
                )
                .await;
            }
            Ok(info) => {
                if get_device_transport(&daemon, &mac).await.is_some() {
                    let d_weak = daemon_weak.clone();
                    let mac_clone = mac.clone();
                    let select_face = !face_selected;
                    let _ = daemon
                        .queue
                        .run(None, async move {
                            if let Some(d) = d_weak.upgrade() {
                                if let Some(dev_t) = get_device_transport(&d, &mac_clone).await {
                                    push_weather(&dev_t, info, select_face).await;
                                }
                            }
                        })
                        .await;
                    // The face is selected for as long as this job keeps the
                    // device. It is re-asserted only after a disconnect, not on
                    // every refresh -- see the note on `face_selected`.
                    face_selected = true;
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
