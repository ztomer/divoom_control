use serde_json::Value;
use std::sync::{Arc, Weak};
use std::time::Duration;

use crate::daemon::{Daemon, DeviceTransport};

mod coordinator;
mod health;
/// macOS-only: it reads now-playing through the `nowplaying` crate, which is
/// itself a macOS-only dependency of this crate (MediaRemote does not exist
/// elsewhere). Gating the MODULE rather than sprinkling cfgs inside it keeps
/// the Linux build honest — R67 briefly broke it by leaving the call sites
/// unguarded after the macOS-only helpers were introduced.
#[cfg(target_os = "macos")]
mod music_job;
mod render;

pub use coordinator::LiveJobCoordinator;
pub use health::{JobHealth, JobState};
#[cfg(target_os = "macos")]
use music_job::run_music;

use render::{get_battery_percent, render_stock, render_sysmon};

/// One call into the now-playing library, isolated so the macOS-only dependency
/// has a single seam and the job body stays readable.
///
/// R67/C2: this replaces `music::get_current_playing_track` +
/// `music::fetch_album_art_url` — an AppleScript sweep over each player
/// followed by an iTunes Search URL guessed from the track name. The guess
/// could not resolve non-album content (YouTube Music, podcasts, live sets) and
/// needed a network round trip in order to fail. MediaRemote returns the exact
/// image the player is displaying, as bytes.
/// Report a job's state on the bus AND into the coordinator's resync store.
///
/// R67: `JobHealth` emits only on transitions, so a UI subscribing after a job
/// starts sees nothing. `live_job_list` answers that, but only if the state is
/// stored — and storing it at each call site separately is how the two would
/// drift. One helper does both halves.
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
    let guard = daemon.device.lock().await;
    if guard.is_some() {
        let cur_id = daemon.device_id.lock().await.clone().unwrap_or_default();
        if cur_id == mac {
            return (*guard).clone();
        }
    }
    None
}

// --- Live Widgets Loops ---

async fn run_sysmon(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    const JOB_KIND: &str = "sysmon";
    let size = params.get("size").and_then(|v| v.as_u64()).unwrap_or(16) as u32;
    let mut sys = sysinfo::System::new_all();

    // R67/C4: a job with no device used to push nothing, say nothing, and
    // sleep its full interval. It now reports its state on every change and
    // re-checks briskly while waiting.
    let health = daemon_weak
        .upgrade()
        .map(|d| health::JobHealth::new("sysmon", &mac, d.tx.clone()));
    let normal_interval = Duration::from_secs(5);

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

        sys.refresh_cpu();
        sys.refresh_memory();

        let cpu = sys.global_cpu_info().cpu_usage() as u8;
        let total_mem = sys.total_memory();
        let used_mem = sys.used_memory();
        let mem = if total_mem > 0 {
            ((used_mem as f64 / total_mem as f64) * 100.0) as u8
        } else {
            0
        };
        let battery = get_battery_percent().unwrap_or(100);

        let rgb = render_sysmon(cpu, mem, battery, size);

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
    let size = params.get("size").and_then(|v| v.as_u64()).unwrap_or(16) as u32;
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

        let api_url = format!(
            "https://query1.finance.yahoo.com/v8/finance/chart/{}",
            symbol
        );
        let res = client
            .get(&api_url)
            .timeout(Duration::from_secs(5))
            .send()
            .await;

        if let Ok(resp) = res {
            if let Ok(body) = resp.json::<serde_json::Value>().await {
                if let Some(result) = body
                    .get("chart")
                    .and_then(|c| c.get("result"))
                    .and_then(|r| r.as_array())
                {
                    if let Some(meta) = result.first().and_then(|r| r.get("meta")) {
                        let price = meta
                            .get("regularMarketPrice")
                            .and_then(|v| v.as_f64())
                            .unwrap_or(0.0);
                        let prev_close = meta
                            .get("chartPreviousClose")
                            .and_then(|v| v.as_f64())
                            .unwrap_or(0.0);
                        let change = price - prev_close;

                        let rgb = render_stock(&symbol, price, change, size);

                        if get_device_transport(&daemon, &mac).await.is_some() {
                            let d_weak = daemon_weak.clone();
                            let mac_clone = mac.clone();
                            let _ = daemon
                                .queue
                                .run(None, async move {
                                    if let Some(d) = d_weak.upgrade() {
                                        if let Some(dev_t) =
                                            get_device_transport(&d, &mac_clone).await
                                        {
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
    let normal_interval = Duration::from_secs(15 * 60);

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
                    let _ = daemon
                        .queue
                        .run(None, async move {
                            if let Some(d) = d_weak.upgrade() {
                                if let Some(dev_t) = get_device_transport(&d, &mac_clone).await {
                                    let _ = dev_t
                                        .send_command(
                                            0x32,
                                            &[0x01, 0x00, 0xFF, 0xFF, 0xFF, 0x00],
                                            false,
                                        )
                                        .await;
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
                            }
                        })
                        .await;
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
