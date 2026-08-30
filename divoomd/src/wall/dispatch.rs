//! Wall-targeted `device_call` dispatch.
//!
//! # Why this exists (R67)
//!
//! `DaemonDeviceProxy(target="wall")` has always sent `target: "wall"` on every
//! wall operation, and `cmd_device_call` never read it — every call went to the
//! single connected device instead, or failed with "no device connected". The
//! `DivoomWall` methods were therefore unreachable: dead code that looked live.
//!
//! This routes the wall-targeted subset to the wall. It is deliberately a small,
//! explicit allowlist rather than a catch-all: a wall is several devices, and
//! most device operations (reading state back, per-device settings) have no
//! sensible wall-wide meaning. An unsupported method must SAY it is unsupported
//! rather than silently do nothing, or we recreate the bug this fixes one layer
//! up.

use crate::daemon::Daemon;
use crate::protocol::{err_reply, Request};
use serde_json::{json, Value};

impl Daemon {
    pub(crate) async fn wall_device_call(&self, req: &Request) -> Value {
        let method = match req.args.get("method").and_then(|v| v.as_str()) {
            Some(m) => m,
            None => return err_reply("device_call requires 'method'"),
        };
        let args = req
            .args
            .get("args")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let kw = req.args.get("kwargs").and_then(|v| v.as_object());

        let guard = self.wall.lock().await;
        let wall = match guard.as_ref() {
            Some(w) => w,
            None => return err_reply("no wall configured"),
        };

        // Read a positional-or-keyword integer, by TRUE position (R67/C7).
        let num = |idx: usize, name: &str, default: i64| -> i64 {
            args.get(idx)
                .and_then(|v| v.as_i64())
                .or_else(|| kw.and_then(|m| m.get(name)).and_then(|v| v.as_i64()))
                .unwrap_or(default)
        };
        let text = |idx: usize, name: &str| -> Option<String> {
            args.get(idx)
                .and_then(|v| v.as_str())
                .or_else(|| kw.and_then(|m| m.get(name)).and_then(|v| v.as_str()))
                .map(str::to_string)
        };

        let strip = |m: &str| m.rsplit('.').next().unwrap_or(m).to_string();
        let ok = match strip(method).as_str() {
            "show_image" | "display_image" => {
                let path = match text(0, "file_path").or_else(|| text(0, "path")) {
                    Some(p) => p,
                    None => return err_reply("wall show_image requires a path"),
                };
                let img_data = match std::fs::read(&path) {
                    Ok(d) => d,
                    Err(e) => return err_reply(&format!("wall show_image: read {path}: {e}")),
                };
                let time_ms = num(1, "time", 100) as u16;
                let daemon_arc = match self.self_weak.get().and_then(|w| w.upgrade()) {
                    Some(d) => d,
                    None => return err_reply("daemon self reference unavailable"),
                };
                wall.show_image(daemon_arc, &img_data, time_ms).await
            }
            "show_light" | "set_light" => {
                let color = text(0, "color").unwrap_or_else(|| "#FFFFFF".to_string());
                let rgb = crate::packets::parse_hex_color(&color).unwrap_or([0xFF, 0xFF, 0xFF]);
                let brightness = num(1, "brightness", 100).clamp(0, 100) as u8;
                let kind = crate::packets::LightingType::from_i64(num(3, "lightning_type", 0));
                wall.set_light(rgb, brightness, kind).await
            }
            "show_clock" => wall.show_clock(num(0, "clock", 0).clamp(0, 15) as u8).await,
            "show_effects" => {
                wall.show_effects(num(0, "number", 0).clamp(0, 255) as u8)
                    .await
            }
            "show_visualization" => {
                wall.show_visualization(num(0, "number", 0).clamp(0, 255) as u8)
                    .await
            }
            "set_brightness" => {
                wall.set_brightness(num(0, "brightness", 100).clamp(0, 100) as u8)
                    .await
            }
            "set_volume" => {
                wall.set_volume(num(0, "volume", 8).clamp(0, 15) as u8)
                    .await
            }
            "switch_channel" => {
                let ch = text(0, "channel").unwrap_or_default().to_lowercase();
                wall.switch_channel(&ch).await
            }
            other => {
                // Honest refusal. Silently returning success for something the
                // wall cannot do is exactly the failure this module fixes.
                return err_reply(&format!(
                    "'{other}' is not supported on a Virtual Wall (a wall is several \
                     devices; per-device reads and settings have no wall-wide meaning)"
                ));
            }
        };

        // `degraded_slots` names the panels that did not take the command, so a
        // partial success is reported as partial rather than as success.
        let degraded = wall.degraded_slots();
        if ok && degraded.is_empty() {
            json!({"success": true, "result": true})
        } else {
            json!({"success": false, "result": false, "degraded": degraded,
                   "error": "one or more wall panels did not accept the command"})
        }
    }
}
