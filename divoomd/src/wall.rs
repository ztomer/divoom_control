//! Multi-device display wall coordinator — ported from `divoom_lib/wall.py`.
//! Coordinates multiple screens arranged in a 2D grid as a unified display.

use image::imageops::FilterType;
use std::collections::HashMap;
use std::sync::Arc;

use crate::daemon::{Daemon, DeviceTransport};

mod cmds;
mod dispatch;
pub(crate) use cmds::cmd_wall_configure;

pub struct WallConfig {
    pub mac: String,
    pub x: i32,
    pub y: i32,
    pub size: i32,
    pub width: Option<i32>,
    pub height: Option<i32>,
}

pub struct DeviceSlot {
    pub device: Option<Arc<DeviceTransport>>,
    pub mac: String,
    pub x: i32,
    pub y: i32,
    pub size: i32,
    pub width: Option<i32>,
    pub height: Option<i32>,
}

pub struct DivoomWall {
    pub devices: Vec<DeviceSlot>,
    pub total_width: i32,
    pub total_height: i32,
    pub min_x: i32,
    pub min_y: i32,
    pub grid_unit_size: i32,
    pub is_free_form: bool,
}

impl DivoomWall {
    pub async fn connect(
        daemon: &Daemon,
        configs: &[WallConfig],
        existing: &HashMap<String, Arc<DeviceTransport>>,
    ) -> Result<Self, String> {
        let is_free_form = configs.iter().any(|c| c.width.is_some());
        let (min_x, min_y, total_width, total_height, grid_unit_size);

        if is_free_form {
            min_x = configs.iter().map(|c| c.x).min().unwrap_or(0);
            min_y = configs.iter().map(|c| c.y).min().unwrap_or(0);
            let max_x = configs
                .iter()
                .map(|c| c.x + c.width.unwrap_or(120))
                .max()
                .unwrap_or(0);
            let max_y = configs
                .iter()
                .map(|c| c.y + c.height.unwrap_or(120))
                .max()
                .unwrap_or(0);
            total_width = max_x - min_x;
            total_height = max_y - min_y;
            grid_unit_size = configs.first().map(|c| c.size).unwrap_or(16);
        } else {
            let mut max_x_slot = 0;
            let mut max_y_slot = 0;
            for cfg in configs {
                if cfg.x + 1 > max_x_slot {
                    max_x_slot = cfg.x + 1;
                }
                if cfg.y + 1 > max_y_slot {
                    max_y_slot = cfg.y + 1;
                }
            }
            grid_unit_size = configs.first().map(|c| c.size).unwrap_or(16);
            total_width = max_x_slot * grid_unit_size;
            total_height = max_y_slot * grid_unit_size;
            min_x = 0;
            min_y = 0;
        }

        #[cfg(feature = "ble")]
        let central = daemon.central().await.ok();

        let mut results = Vec::new();
        for cfg in configs {
            let mac = cfg.mac.clone();
            if let Some(existing_dev) = existing.get(&mac) {
                let dev = existing_dev.clone();
                results.push(tokio::spawn(async move { (mac, Ok(dev)) }));
            } else {
                #[cfg(feature = "ble")]
                if let Some(ref c) = central {
                    let c_clone = c.clone();
                    let m_clone = mac.clone();
                    results.push(tokio::spawn(async move {
                        match crate::ble::BleTransport::connect(&c_clone, &m_clone).await {
                            Ok(ble_dev) => (m_clone, Ok(Arc::new(DeviceTransport::Ble(ble_dev)))),
                            Err(e) => (m_clone, Err(e.to_string())),
                        }
                    }));
                    continue;
                }
                results.push(tokio::spawn(async move {
                    (mac, Err("BLE support disabled or unavailable".to_string()))
                }));
            }
        }

        let mut join_results = Vec::new();
        for task in results {
            if let Ok(r) = task.await {
                join_results.push(r);
            }
        }

        let mut devices = Vec::new();
        let mut connected_count = 0;

        for (idx, (mac, res)) in join_results.into_iter().enumerate() {
            let cfg = &configs[idx];
            let slot_device = match res {
                Ok(dev) => {
                    connected_count += 1;
                    Some(dev)
                }
                _ => None,
            };
            devices.push(DeviceSlot {
                device: slot_device,
                mac,
                x: cfg.x,
                y: cfg.y,
                size: cfg.size,
                width: cfg.width,
                height: cfg.height,
            });
        }

        if connected_count == 0 && !configs.is_empty() {
            return Err("All wall slots failed to connect".to_string());
        }

        Ok(DivoomWall {
            devices,
            total_width,
            total_height,
            min_x,
            min_y,
            grid_unit_size,
            is_free_form,
        })
    }

    pub async fn disconnect(&self) {
        let mut tasks = Vec::new();
        for slot in &self.devices {
            if let Some(ref dev) = slot.device {
                let dev_clone = dev.clone();
                tasks.push(tokio::spawn(async move {
                    match &*dev_clone {
                        #[cfg(feature = "ble")]
                        DeviceTransport::Ble(b) => {
                            let _ = b.disconnect().await;
                        }
                        DeviceTransport::Spp(s) => {
                            let _ = s.disconnect().await;
                        }
                        DeviceTransport::Lan(_) => {}
                        DeviceTransport::Mock(_) => {}
                    }
                }));
            }
        }
        for task in tasks {
            let _ = task.await;
        }
    }

    pub fn is_connected(&self) -> bool {
        self.devices.iter().all(|s| s.device.is_some())
    }

    pub fn degraded_slots(&self) -> Vec<String> {
        self.devices
            .iter()
            .filter(|s| s.device.is_none())
            .map(|s| s.mac.clone())
            .collect()
    }

    pub async fn show_image(
        &self,
        daemon: Arc<Daemon>,
        img_data: &[u8],
        default_time_ms: u16,
    ) -> bool {
        let is_gif = img_data.len() >= 3 && &img_data[0..3] == b"GIF";

        // Ensure encoder exists before spawning tasks
        if daemon.encoder().is_none() {
            return false;
        }

        let mut tasks = Vec::new();
        for slot in &self.devices {
            let dev = match slot.device {
                Some(ref d) => d.clone(),
                None => continue,
            };

            let left = if self.is_free_form {
                slot.x - self.min_x
            } else {
                slot.x * slot.size
            };
            let upper = if self.is_free_form {
                slot.y - self.min_y
            } else {
                slot.y * slot.size
            };
            let width = slot.width.unwrap_or(slot.size);
            let height = slot.height.unwrap_or(slot.size);

            let data_vec = img_data.to_vec();
            let total_w = self.total_width;
            let total_h = self.total_height;
            let is_ff = self.is_free_form;
            let size = slot.size;
            let daemon_clone = daemon.clone();

            tasks.push(tokio::spawn(async move {
                let frames = tokio::task::spawn_blocking(move || {
                    process_wall_image(
                        &data_vec,
                        is_gif,
                        width,
                        height,
                        left,
                        upper,
                        size,
                        total_w,
                        total_h,
                        is_ff,
                        default_time_ms,
                    )
                })
                .await
                .map_err(|e| e.to_string())??;

                let enc = match daemon_clone.encoder() {
                    Some(e) => e,
                    None => return Err("encoder not available".to_string()),
                };

                let mut blob = Vec::new();
                for (rgb, w, h, t) in &frames {
                    let frame_body = if *w == 32 && *h == 32 {
                        enc.encode_animation_frame_32(rgb, *w, *h, *t)
                    } else {
                        enc.encode_animation_frame(rgb, *w, *h, *t)
                    };
                    if let Some(b) = frame_body {
                        blob.extend_from_slice(&b);
                    } else {
                        return Err("Encode failed".to_string());
                    }
                }

                match &*dev {
                    DeviceTransport::Lan(_) => {
                        Err("LAN not supported for wall show_image".to_string())
                    }
                    _ => {
                        let _ = dev
                            .send_command(0x45, &[0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0], false)
                            .await;
                        dev.stream_animation_8b(&blob)
                            .await
                            .map_err(|e| e.to_string())
                    }
                }
            }));
        }

        let mut ok = true;
        for task in tasks {
            match task.await {
                Ok(Ok(true)) => {}
                _ => {
                    ok = false;
                }
            }
        }
        ok && self.degraded_slots().is_empty()
    }

    /// R67: this hand-built `[0x01, brightness, R, G, B, 0x01]` — with
    /// BRIGHTNESS AND RGB TRANSPOSED against the canonical
    /// `[channel, R, G, B, brightness, type, power, 0, 0, 0]`, only six bytes
    /// instead of ten, and the trailing `0x01` landing in the lighting-TYPE
    /// slot rather than power. So a wall ambient push sent the wrong colour,
    /// the wrong brightness and mode "Love". The Python wall never had this
    /// bug because it DELEGATES to `display.show_light`; the port re-derived
    /// the payload by hand and got it wrong.
    pub async fn set_light(
        &self,
        color: [u8; 3],
        brightness: u8,
        kind: crate::packets::LightingType,
    ) -> bool {
        let packet = crate::packets::LightPacket {
            rgb: color,
            brightness,
            kind,
            power: true,
        };
        self.broadcast_command(crate::packets::CMD_SET_LIGHT_MODE, &packet.to_bytes())
            .await
    }

    pub async fn show_clock(&self, clock: u8) -> bool {
        let packet = crate::packets::ClockPacket {
            style: clock,
            ..Default::default()
        };
        self.broadcast_command(crate::packets::CMD_SET_LIGHT_MODE, &packet.to_bytes())
            .await
    }

    /// R67: was `[0x03, number]` — two bytes, and NOT 1-indexed. The device
    /// needs the full ten (see the padding notes in
    /// `divoom_lib/display/__init__.py`) and VJ effects are 1-indexed on BLE,
    /// so this sent the wrong effect in a packet the device may ignore outright.
    pub async fn show_effects(&self, number: u8) -> bool {
        self.broadcast_command(
            crate::packets::CMD_SET_LIGHT_MODE,
            &crate::packets::vj_effect(number),
        )
        .await
    }

    /// R67: was `[0x04, number]` — two bytes where the device needs ten.
    pub async fn show_visualization(&self, number: u8) -> bool {
        self.broadcast_command(
            crate::packets::CMD_SET_LIGHT_MODE,
            &crate::packets::visualization(number),
        )
        .await
    }

    pub async fn set_brightness(&self, brightness: u8) -> bool {
        self.broadcast_command(0x74, &[brightness]).await
    }

    pub async fn set_volume(&self, volume: u8) -> bool {
        self.broadcast_command(0x08, &[volume]).await
    }

    pub async fn switch_channel(&self, channel: &str) -> bool {
        let val = match channel {
            "clock" => 0x00,
            "light" => 0x01,
            "cloud" => 0x02,
            "vj" => 0x03,
            "eq" => 0x04,
            "image" => 0x05,
            "scoreboard" => 0x06,
            _ => return false,
        };
        self.broadcast_command(0x45, &[val, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            .await
    }

    async fn broadcast_command(&self, command_id: u8, args: &[u8]) -> bool {
        let mut tasks = Vec::new();
        for slot in &self.devices {
            if let Some(ref dev) = slot.device {
                let dev_clone = dev.clone();
                let args_vec = args.to_vec();
                tasks.push(tokio::spawn(async move {
                    match &*dev_clone {
                        DeviceTransport::Lan(_) => false,
                        _ => dev_clone
                            .send_command(command_id, &args_vec, true)
                            .await
                            .is_ok(),
                    }
                }));
            }
        }
        let mut ok = true;
        for task in tasks {
            if let Ok(res) = task.await {
                if !res {
                    ok = false;
                }
            } else {
                ok = false;
            }
        }
        ok && self.degraded_slots().is_empty()
    }
}

#[expect(clippy::too_many_arguments)]
fn process_wall_image(
    data: &[u8],
    is_gif: bool,
    slot_width: i32,
    slot_height: i32,
    slot_left: i32,
    slot_upper: i32,
    slot_size: i32,
    total_width: i32,
    total_height: i32,
    is_free_form: bool,
    default_time_ms: u16,
) -> Result<Vec<crate::image_proc::Frame>, String> {
    if is_gif {
        use image::codecs::gif::GifDecoder;
        use image::AnimationDecoder;
        let decoder =
            GifDecoder::new(std::io::Cursor::new(data)).map_err(|e| format!("gif decoder: {e}"))?;
        let gif_frames = decoder
            .into_frames()
            .collect_frames()
            .map_err(|e| format!("gif frames: {e}"))?;
        if gif_frames.is_empty() {
            return Err("GIF has no frames".into());
        }
        let mut out = Vec::with_capacity(gif_frames.len());
        for frame in gif_frames {
            let (numer, denom) = frame.delay().numer_denom_ms();
            let time_ms = if denom == 0 {
                default_time_ms
            } else {
                ((numer / denom.max(1)) as u16).max(50)
            };
            let rgba = frame.into_buffer();
            let mut img = image::DynamicImage::ImageRgba8(rgba);
            img = img.resize_exact(total_width as u32, total_height as u32, FilterType::Nearest);
            let mut cropped = img.crop_imm(
                slot_left as u32,
                slot_upper as u32,
                slot_width as u32,
                slot_height as u32,
            );
            if is_free_form {
                cropped =
                    cropped.resize_exact(slot_size as u32, slot_size as u32, FilterType::Nearest);
            }
            let rgb = cropped.to_rgb8().into_raw();
            out.push((rgb, slot_size, slot_size, time_ms));
        }
        Ok(out)
    } else {
        let mut img = image::load_from_memory(data).map_err(|e| format!("image load: {e}"))?;
        img = img.resize_exact(total_width as u32, total_height as u32, FilterType::Nearest);
        let mut cropped = img.crop_imm(
            slot_left as u32,
            slot_upper as u32,
            slot_width as u32,
            slot_height as u32,
        );
        if is_free_form {
            cropped = cropped.resize_exact(slot_size as u32, slot_size as u32, FilterType::Nearest);
        }
        let rgb = cropped.to_rgb8().into_raw();
        Ok(vec![(rgb, slot_size, slot_size, default_time_ms)])
    }
}
