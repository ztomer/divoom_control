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

/// Every method the wall answers, by the name its `match` below takes (a
/// dotted path is cut to its last segment first). Declared so a client can be
/// held to it: the GUI's wall calls and its tests' fakes are checked against
/// this list (`tests/test_bridge_commands_exist_in_daemon.py`), and the arms
/// are held to the list both ways (`the_table_names_every_arm`). The wall
/// previews were asked for, refused `unsupported` and faked in the tests for
/// as long as no such list existed (P6.5).
pub const WALL_METHODS: &[&str] = &[
    "get_last_previews",
    "show_image",
    "display_image",
    "show_light",
    "set_light",
    "show_clock",
    "set_clock_rich",
    "set_scoreboard",
    "show_effects",
    "show_visualization",
    "set_brightness",
    "set_volume",
    "switch_channel",
];

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

        // A panel's parsers read the integers alone (`device_call/mod.rs`).
        let ints: Vec<i64> = args.iter().filter_map(Value::as_i64).collect();
        let strip = |m: &str| m.rsplit('.').next().unwrap_or(m).to_string();
        let outcome = match strip(method).as_str() {
            "get_last_previews" => return wall.previews.reply(),
            "show_image" | "display_image" => {
                let path = text(0, "file_path").or_else(|| text(0, "path"));
                let art = kw.and_then(|m| m.get("art")).and_then(Value::as_str);
                match push_image(wall, path, art, num(1, "time", 100).word()).await {
                    Ok(outcome) => outcome,
                    Err(refusal) => return refusal,
                }
            }
            "show_light" | "set_light" => {
                let color = text(0, "color").unwrap_or_else(|| "#FFFFFF".to_string());
                let rgb = crate::packets::parse_hex_color(&color).unwrap_or([0xFF, 0xFF, 0xFF]);
                let brightness = num(1, "brightness", 100).clamp(0, 100).byte();
                let kind = crate::packets::LightingType::from_i64(num(3, "lightning_type", 0));
                wall.set_light(rgb, brightness, kind).await
            }
            "show_clock" | "set_clock_rich" => {
                let packet = crate::device_call::basic::clock_packet_from_call(&ints, &args, kw);
                wall.show_clock(&packet).await
            }
            "set_scoreboard" => match crate::device_call::tools::scoreboard_payload(&ints, kw) {
                Ok(payload) => wall.set_scoreboard(&payload).await,
                Err(e) => return err_code(ErrorCode::BadRequest, &e),
            },
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
                     devices; per-device reads and settings have no wall-wide meaning); \
                     it answers {}",
                        WALL_METHODS.join(", ")
                    ),
                );
            }
        };

        wall_outcome(&outcome)
    }
}

/// The wall's `show_image`: the file at `path` on every panel, or the
/// refusal when there is no path or it cannot be read.
async fn push_image(
    wall: &super::DivoomWall,
    path: Option<String>,
    art: Option<&str>,
    time_ms: u16,
) -> Result<super::WallOutcome, Value> {
    // What the image IS (D14): pixel art is cut, never scaled; required.
    let source = crate::art_source::Source::from_wire(art).map_err(|why| {
        err_code(
            ErrorCode::BadRequest,
            &format!("device_call wall show_image: {why}"),
        )
    })?;
    let Some(path) = path else {
        return Err(crate::command_args::missing(
            "device_call wall show_image",
            "'path'",
        ));
    };
    match std::fs::read(&path) {
        Ok(img_data) => wall
            .show_image(&img_data, source, time_ms)
            .await
            .map_err(|e| e.reply("wall show_image", ErrorCode::Unsupported)),
        Err(e) => Err(err_code(
            ErrorCode::BadRequest,
            &format!("wall show_image: read {path}: {e}"),
        )),
    }
}

/// The reply to a wall command, built from what each slot did (P6.3): it
/// names each linked panel whose write failed (`failed`, with the reason)
/// apart from each slot with no panel (`degraded`). It used to take one
/// `bool` for the whole wall, so a failed write named no panel at all.
fn wall_outcome(outcome: &super::WallOutcome) -> Value {
    outcome.reply()
}

#[cfg(test)]
mod tests {
    use super::WALL_METHODS;
    use std::collections::BTreeSet;

    /// Every method name an arm of `wall_device_call`'s `match` takes, read
    /// from this file's source.
    fn arms() -> BTreeSet<String> {
        let src = include_str!("dispatch.rs");
        let start = src.find("let outcome = match").expect("the match");
        let end = start + src[start..].find("other =>").expect("its fallback arm");
        let mut names = BTreeSet::new();
        let mut rest = &src[start..end];
        while let Some(open) = rest.find('"') {
            let after = &rest[open + 1..];
            let Some(close) = after.find('"') else { break };
            let tail = after[close + 1..].trim_start();
            if tail.starts_with("=>") || tail.starts_with('|') {
                names.insert(after[..close].to_string());
            }
            rest = &after[close + 1..];
        }
        names
    }

    #[test]
    fn the_table_names_every_arm() {
        let arms = arms();
        assert!(arms.len() >= 8, "the source walk found the arms: {arms:?}");
        let table: BTreeSet<String> = WALL_METHODS.iter().map(|m| (*m).to_string()).collect();
        assert_eq!(arms, table, "WALL_METHODS and the wall's match arms differ");
    }
}
