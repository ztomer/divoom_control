//! Multi-device display wall coordinator — ported from `divoom_lib/wall.py`.
//! Coordinates multiple screens arranged in a 2D grid as a unified display.

use image::imageops::FilterType;
use std::collections::HashMap;
use std::sync::Arc;

use crate::daemon::{Daemon, DeviceTransport};
use crate::image_encode;

mod bounds;
mod cmds;
mod dispatch;

use bounds::WallBounds;
pub(crate) use cmds::{cmd_get_topology, cmd_set_topology, cmd_wall_configure};

#[derive(Clone, Debug)]
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
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn connect(
        daemon: &Daemon,
        configs: &[WallConfig],
        existing: &HashMap<String, Arc<DeviceTransport>>,
    ) -> Result<Self, String> {
        // `daemon` is the handle to the radio; without `ble` the wall still
        // lays out its grid and reports that it cannot reach any panel.
        #[cfg(not(feature = "ble"))]
        let _ = daemon;
        let is_free_form = configs.iter().any(|c| c.width.is_some());
        let WallBounds {
            min_x,
            min_y,
            total_width,
            total_height,
            grid_unit_size,
        } = WallBounds::from_configs(configs);

        // The CoreBluetooth central is created LAZILY, only once a slot
        // actually needs a fresh radio connection. Creating it up front made
        // a wall built entirely from already-connected (or mock) transports
        // spin up CoreBluetooth for nothing -- and in a process without a
        // Bluetooth grant macOS answers that with SIGABRT, which is how the
        // integration test died in a terminal that lacked the grant while
        // passing in one that had it.
        #[cfg(feature = "ble")]
        let mut central: Option<crate::central::BleCentral> = None;

        let mut results = Vec::new();
        for cfg in configs {
            let cfg_clone = cfg.clone();
            let mac = cfg.mac.clone();
            if let Some(existing_dev) = existing.get(&mac) {
                let dev = existing_dev.clone();
                results.push(tokio::spawn(async move { (cfg_clone, Ok(dev)) }));
            } else {
                #[cfg(feature = "ble")]
                if central.is_none() {
                    central = daemon.central().await.ok();
                }
                #[cfg(feature = "ble")]
                if let Some(ref c) = central {
                    let c_clone = c.clone();
                    let m_clone = mac.clone();
                    results.push(tokio::spawn(async move {
                        match crate::ble::BleTransport::connect(&c_clone, &m_clone).await {
                            Ok(ble_dev) => (cfg_clone, Ok(Arc::new(DeviceTransport::Ble(ble_dev)))),
                            Err(e) => (cfg_clone, Err(e.to_string())),
                        }
                    }));
                    continue;
                }
                results.push(tokio::spawn(async move {
                    (
                        cfg_clone,
                        Err("BLE support disabled or unavailable".to_string()),
                    )
                }));
            }
        }

        let mut devices = Vec::new();
        let mut connected_count = 0;
        for task in results {
            if let Ok((cfg, res)) = task.await {
                let slot_device = res.ok().inspect(|_| {
                    connected_count += 1;
                });
                devices.push(DeviceSlot {
                    device: slot_device,
                    mac: cfg.mac,
                    x: cfg.x,
                    y: cfg.y,
                    size: cfg.size,
                    width: cfg.width,
                    height: cfg.height,
                });
            }
        }

        if connected_count == 0 && !configs.is_empty() {
            return Err("All wall slots failed to connect".to_string());
        }

        Ok(Self {
            devices,
            total_width,
            total_height,
            min_x,
            min_y,
            grid_unit_size,
            is_free_form,
        })
    }

    pub async fn disconnect(&self, preserved_macs: &[String]) {
        let mut tasks = Vec::new();
        for slot in &self.devices {
            if preserved_macs
                .iter()
                .any(|m| m.eq_ignore_ascii_case(&slot.mac))
            {
                continue;
            }
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
                        DeviceTransport::Lan(_) | DeviceTransport::Mock(_) => {}
                    }
                }));
            }
        }
        for task in tasks {
            let _ = task.await;
        }
    }

    #[must_use]
    pub fn is_connected(&self) -> bool {
        self.devices.iter().all(|s| s.device.is_some())
    }

    #[must_use]
    pub fn degraded_slots(&self) -> Vec<String> {
        self.devices
            .iter()
            .filter(|s| s.device.is_none())
            .map(|s| s.mac.clone())
            .collect()
    }

    /// Show an image on every panel in this wall.
    ///
    /// The `daemon` parameter is gone: it existed to reach the C encoder
    /// through `Daemon::encoder()`, and `image_encode` is a free function now.
    pub async fn show_image(&self, img_data: &[u8], default_time_ms: u16) -> bool {
        let is_gif = img_data.len() >= 3 && &img_data[0..3] == b"GIF";

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
            let cut = SlotCut {
                width: slot.width.unwrap_or(slot.size),
                height: slot.height.unwrap_or(slot.size),
                left,
                upper,
                size: slot.size,
                total_width: self.total_width,
                total_height: self.total_height,
                is_free_form: self.is_free_form,
            };

            let data_vec = img_data.to_vec();

            tasks.push(tokio::spawn(async move {
                let frames = tokio::task::spawn_blocking(move || {
                    process_wall_image(&data_vec, is_gif, &cut, default_time_ms)
                })
                .await
                .map_err(|e| e.to_string())??;

                let mut blob = Vec::new();
                for (rgb, w, h, t) in &frames {
                    // No 32x32 branch, and no dylib: the Rust encoder emits the
                    // same bytes for a 32x32 panel as the 32x32 entry point did
                    // (`image_encode::encode_animation_frame_32` delegates to
                    // this very function, and the recorded vectors pin both
                    // against the C), so choosing between them was ceremony.
                    let frame_body = image_encode::encode_animation_frame(rgb, *w, *h, *t)
                        .map_err(|why| format!("encode {w}x{h} failed: {why}"))?;
                    blob.extend_from_slice(&frame_body);
                }

                if let DeviceTransport::Lan(_) = &*dev {
                    Err("LAN not supported for wall show_image".to_string())
                } else {
                    let _ = dev
                        .send_command(0x45, &[0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0], false)
                        .await;
                    dev.stream_animation_8b(&blob)
                        .await
                        .map_err(|e| e.to_string())
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

/// Configured wall geometry is non-negative; a negative here previously
/// wrapped to a multi-gigabyte allocation and panicked downstream, so it
/// fails fast with its name attached instead.
fn dim(x: i32) -> u32 {
    u32::try_from(x).expect("wall geometry is non-negative")
}

/// One slot's cut of the wall image: the wall the image is scaled to, and the
/// rectangle of it this device shows (resized to `size` square in a free-form
/// wall).
#[derive(Debug, Clone, Copy)]
struct SlotCut {
    width: i32,
    height: i32,
    left: i32,
    upper: i32,
    size: i32,
    total_width: i32,
    total_height: i32,
    is_free_form: bool,
}

impl SlotCut {
    /// The wall-sized image cropped to this slot (and squared in a free-form
    /// wall), as raw RGB.
    fn cut(&self, img: &image::DynamicImage) -> Vec<u8> {
        let scaled = img.resize_exact(
            dim(self.total_width),
            dim(self.total_height),
            FilterType::Nearest,
        );
        let mut cropped = scaled.crop_imm(
            dim(self.left),
            dim(self.upper),
            dim(self.width),
            dim(self.height),
        );
        if self.is_free_form {
            cropped = cropped.resize_exact(dim(self.size), dim(self.size), FilterType::Nearest);
        }
        cropped.to_rgb8().into_raw()
    }
}

fn process_wall_image(
    data: &[u8],
    is_gif: bool,
    cut: &SlotCut,
    default_time_ms: u16,
) -> Result<Vec<crate::image_proc::Frame>, String> {
    let slot_size = cut.size;
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
                u16::try_from(numer / denom.max(1))
                    .unwrap_or(u16::MAX)
                    .max(50)
            };
            let rgb = cut.cut(&image::DynamicImage::ImageRgba8(frame.into_buffer()));
            out.push((rgb, slot_size, slot_size, time_ms));
        }
        Ok(out)
    } else {
        let img = image::load_from_memory(data).map_err(|e| format!("image load: {e}"))?;
        Ok(vec![(cut.cut(&img), slot_size, slot_size, default_time_ms)])
    }
}
