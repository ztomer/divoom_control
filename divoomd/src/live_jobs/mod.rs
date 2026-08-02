use serde_json::Value;
use std::sync::{Arc, Weak};
use std::time::Duration;

use crate::daemon::{Daemon, DeviceTransport};

mod coordinator;
mod music;
mod render;

pub use coordinator::LiveJobCoordinator;

use music::{fetch_album_art_url, get_current_playing_track};
use render::{get_battery_percent, render_stock, render_sysmon};

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
    let size = params.get("size").and_then(|v| v.as_u64()).unwrap_or(16) as u32;
    let mut sys = sysinfo::System::new_all();

    loop {
        let daemon = match daemon_weak.upgrade() {
            Some(d) => d,
            None => break,
        };

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

        tokio::time::sleep(Duration::from_secs(5)).await;
    }
}

async fn run_stocks(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
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

    loop {
        let daemon = match daemon_weak.upgrade() {
            Some(d) => d,
            None => break,
        };

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

        tokio::time::sleep(Duration::from_secs(15)).await;
    }
}

async fn run_weather(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    let location = params
        .get("location")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let client = reqwest::Client::new();

    loop {
        let daemon = match daemon_weak.upgrade() {
            Some(d) => d,
            None => break,
        };

        let mut url = "https://wttr.in/".to_string();
        if !location.is_empty() {
            url.push_str(&location);
        }

        let res = client
            .get(&url)
            .query(&[("format", "j1")])
            .timeout(Duration::from_secs(8))
            .send()
            .await;

        if let Ok(resp) = res {
            if resp.status() == 200 {
                if let Ok(body) = resp.json::<serde_json::Value>().await {
                    if let Some(current) = body
                        .get("current_condition")
                        .and_then(|c| c.as_array())
                        .and_then(|a| a.first())
                    {
                        let temp_str = current
                            .get("temp_C")
                            .and_then(|v| v.as_str())
                            .unwrap_or("0");
                        let code_str = current
                            .get("weatherCode")
                            .and_then(|v| v.as_str())
                            .unwrap_or("113");

                        let temp_c = temp_str.parse::<i8>().unwrap_or(0);
                        let weather_code = code_str.parse::<i32>().unwrap_or(113);

                        let weather_type = match weather_code {
                            113 => 1,                   // Clear
                            116 | 119 | 122 => 3,       // CloudySky
                            143 | 185 | 248 | 260 => 9, // Fog
                            176 | 263 | 266 | 281 | 284 | 293 | 296 | 299 | 302 | 305 | 308
                            | 311 | 314 | 353 | 356 | 359 => 6, // Rain
                            179 | 182 | 227 | 230 | 317 | 320 | 323 | 326 | 329 | 332 | 335
                            | 338 | 350 | 362 | 365 | 368 | 371 | 374 | 377 => 8, // Snow
                            200 | 386 | 389 | 392 | 395 => 5, // Thunderstorm
                            _ => 1,                     // Default to Clear
                        };

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
                                            let _ = dev_t
                                                .send_command(
                                                    0x32,
                                                    &[0x01, 0x00, 0xFF, 0xFF, 0xFF, 0x00],
                                                    false,
                                                )
                                                .await;
                                            let _ = dev_t
                                                .send_command(
                                                    0x5f,
                                                    &[temp_c as u8, weather_type],
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
            }
        }

        tokio::time::sleep(Duration::from_secs(15 * 60)).await;
    }
}

async fn run_music(daemon_weak: Weak<Daemon>, mac: String, params: Value) {
    let size = params.get("size").and_then(|v| v.as_u64()).unwrap_or(16) as u32;
    let client = reqwest::Client::new();

    let mut last_track = String::new();
    let mut last_artist = String::new();

    loop {
        let daemon = match daemon_weak.upgrade() {
            Some(d) => d,
            None => break,
        };

        if let Some(track_info) = get_current_playing_track(&client).await {
            if track_info.track != last_track || track_info.artist != last_artist {
                let mut art_url = track_info.artwork_url;
                if art_url.is_none() {
                    art_url =
                        fetch_album_art_url(&client, &track_info.track, &track_info.artist).await;
                }

                if let Some(url) = art_url {
                    if let Ok(resp) = client.get(&url).send().await {
                        if let Ok(bytes) = resp.bytes().await {
                            if let Ok(frames) =
                                crate::image_proc::process_image_bytes(bytes.to_vec(), size, 100)
                            {
                                if let Some((rgb, w, h, t)) = frames.first() {
                                    if get_device_transport(&daemon, &mac).await.is_some() {
                                        let d_weak = daemon_weak.clone();
                                        let mac_clone = mac.clone();
                                        let rgb_vec = rgb.clone();
                                        let w_val = *w;
                                        let h_val = *h;
                                        let t_val = *t;
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

                                        if success {
                                            last_track = track_info.track.clone();
                                            last_artist = track_info.artist.clone();
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        tokio::time::sleep(Duration::from_millis(1500)).await;
    }
}
