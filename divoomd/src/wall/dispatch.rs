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
use crate::protocol::{err_code, ErrorCode, Request};
use crate::wire::WireNarrow as _;
use serde_json::Value;

impl Daemon {
    pub(crate) async fn wall_device_call(&self, req: &Request) -> Value {
        let Some(method) = req.args.get("method").and_then(|v| v.as_str()) else {
            return crate::command_args::missing("device_call", "'method'");
        };
        let args = req
            .args
            .get("args")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let kw = req.args.get("kwargs").and_then(|v| v.as_object());

        let guard = self.wall.lock().await;
        let Some(wall) = guard.as_ref() else {
            drop(guard);
            return err_code(ErrorCode::NoDevice, "no wall configured");
        };

        // Read a positional-or-keyword integer, by TRUE position (R67/C7).
        let num = |idx: usize, name: &str, default: i64| -> i64 {
            args.get(idx)
                .and_then(serde_json::Value::as_i64)
                .or_else(|| {
                    kw.and_then(|m| m.get(name))
                        .and_then(serde_json::Value::as_i64)
                })
                .unwrap_or(default)
        };
        let text = |idx: usize, name: &str| -> Option<String> {
            args.get(idx)
                .and_then(|v| v.as_str())
                .or_else(|| kw.and_then(|m| m.get(name)).and_then(|v| v.as_str()))
                .map(str::to_string)
        };

        let strip = |m: &str| m.rsplit('.').next().unwrap_or(m).to_string();
        let outcome = match strip(method).as_str() {
            "show_image" | "display_image" => {
                let Some(path) = text(0, "file_path").or_else(|| text(0, "path")) else {
                    return crate::command_args::missing("device_call wall show_image", "'path'");
                };
                let img_data = match std::fs::read(&path) {
                    Ok(d) => d,
                    Err(e) => {
                        return err_code(
                            ErrorCode::BadRequest,
                            &format!("wall show_image: read {path}: {e}"),
                        )
                    }
                };
                let time_ms = num(1, "time", 100).word();
                wall.show_image(&img_data, time_ms).await
            }
            "show_light" | "set_light" => {
                let color = text(0, "color").unwrap_or_else(|| "#FFFFFF".to_string());
                let rgb = crate::packets::parse_hex_color(&color).unwrap_or([0xFF, 0xFF, 0xFF]);
                let brightness = num(1, "brightness", 100).clamp(0, 100).byte();
                let kind = crate::packets::LightingType::from_i64(num(3, "lightning_type", 0));
                wall.set_light(rgb, brightness, kind).await
            }
            "show_clock" => {
                wall.show_clock(num(0, "clock", 0).clamp(0, 15).byte())
                    .await
            }
            "show_effects" => {
                wall.show_effects(num(0, "number", 0).clamp(0, 255).byte())
                    .await
            }
            "show_visualization" => {
                wall.show_visualization(num(0, "number", 0).clamp(0, 255).byte())
                    .await
            }
            "set_brightness" => {
                wall.set_brightness(num(0, "brightness", 100).clamp(0, 100).byte())
                    .await
            }
            "set_volume" => {
                wall.set_volume(num(0, "volume", 8).clamp(0, 15).byte())
                    .await
            }
            "switch_channel" => {
                let ch = text(0, "channel").unwrap_or_default();
                let Some(packet) = crate::packets::channel_payload(&ch) else {
                    return err_code(
                        ErrorCode::BadRequest,
                        &format!("wall switch_channel: unknown channel '{ch}'"),
                    );
                };
                wall.switch_channel(&packet).await
            }
            other => {
                // Honest refusal. Silently returning success for something the
                // wall cannot do is exactly the failure this module fixes.
                return err_code(
                    ErrorCode::Unsupported,
                    &format!(
                        "'{other}' is not supported on a Virtual Wall (a wall is several \
                     devices; per-device reads and settings have no wall-wide meaning)"
                    ),
                );
            }
        };

        wall_outcome(&outcome)
    }
}

/// The reply to a wall command, built from what each slot did (P6.3): it
/// names each linked panel whose write failed (`failed`, with the reason)
/// apart from each slot with no panel (`degraded`). It used to take one
/// `bool` for the whole wall, so a failed write named no panel at all.
fn wall_outcome(outcome: &super::WallOutcome) -> Value {
    outcome.reply()
}
