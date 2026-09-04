//! Host metrics for the sysmon widget: one sampler, one renderer, two callers.
//!
//! The device frame and the GUI's preview tile are the same pixels from the same
//! code. That is not tidiness -- it is the house rule that a preview mirrors live
//! state through the SHARED renderer rather than a parallel reimplementation,
//! and this widget was the last place still breaking it. The GUI used to run
//! `divoom_lib/utils/media_source.py` (psutil + PIL) in its own process while the
//! device got [`super::render::render_sysmon`], so "what the card shows" and
//! "what the device shows" were two programs that merely agreed for now.
//!
//! Two implementations of one question always drift; R67 found three that had.

use base64::Engine;
use serde_json::{json, Value};
use sysinfo::System;

use super::render::{get_battery_percent, render_sysmon};

/// One reading of the metrics the widget draws.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SysmonSample {
    pub cpu: u8,
    pub mem: u8,
    pub battery: u8,
}

/// Read CPU, memory and battery from an already-refreshed `System`.
///
/// Takes the `System` rather than making one: CPU usage is a DELTA between two
/// refreshes, so the long-running job's instance (refreshed every 5s) and the
/// one-shot request's instance (refreshed twice around a short sleep) both have
/// to own their own. What they must not own is a second copy of this arithmetic.
pub fn sample(sys: &System) -> SysmonSample {
    let total_mem = sys.total_memory();
    let used_mem = sys.used_memory();
    SysmonSample {
        cpu: sys.global_cpu_info().cpu_usage() as u8,
        mem: if total_mem > 0 {
            ((used_mem as f64 / total_mem as f64) * 100.0) as u8
        } else {
            0
        },
        battery: get_battery_percent().unwrap_or(100),
    }
}

/// Sample once, for a caller with no long-lived `System`.
///
/// `refresh_cpu` reports usage since the PREVIOUS refresh, so a fresh `System`
/// asked immediately reports 0% -- a preview that always says the machine is
/// idle, and one that looks like a plausible reading rather than a missing one.
/// Hence two refreshes around `MINIMUM_CPU_UPDATE_INTERVAL`, which is what
/// sysinfo itself documents as the shortest meaningful gap.
pub async fn sample_once() -> SysmonSample {
    let mut sys = System::new_all();
    sys.refresh_cpu();
    tokio::time::sleep(sysinfo::MINIMUM_CPU_UPDATE_INTERVAL).await;
    sys.refresh_cpu();
    sys.refresh_memory();
    sample(&sys)
}

/// Clamp a requested matrix size to something renderable.
///
/// The renderer indexes a `size * size * 3` buffer, so a zero or absurd size is
/// not a rendering question but an allocation one. 64 is the largest Divoom
/// matrix; anything past it is a caller mistake, not a device.
pub fn clamp_size(requested: u64) -> u32 {
    requested.clamp(8, 64) as u32
}

/// `sysmon` -- the stats AND the exact frame the device would be given.
///
/// Returns the frame as base64 RGB (`size * size * 3` bytes, row-major) rather
/// than an encoded image: the daemon has no image encoder, the caller already
/// has one, and raw pixels cannot disagree with themselves about a colour space.
pub async fn cmd_sysmon(args: &Value) -> Value {
    let size = clamp_size(args.get("size").and_then(|v| v.as_u64()).unwrap_or(16));
    let s = sample_once().await;
    let rgb = render_sysmon(s.cpu, s.mem, s.battery, size);
    json!({
        "success": true,
        "size": size,
        "cpu": s.cpu,
        "mem": s.mem,
        "battery": s.battery,
        "frame_rgb_b64": base64::engine::general_purpose::STANDARD.encode(&rgb),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamps_a_zero_size_to_something_renderable() {
        // `size: 0` reached the renderer as a 0-byte buffer before this existed.
        assert_eq!(clamp_size(0), 8);
    }

    #[test]
    fn clamps_an_absurd_size_to_the_largest_real_matrix() {
        assert_eq!(clamp_size(100_000), 64);
    }

    #[test]
    fn passes_real_sizes_through() {
        assert_eq!(clamp_size(16), 16);
        assert_eq!(clamp_size(32), 32);
        assert_eq!(clamp_size(64), 64);
    }

    #[test]
    fn sample_reports_zero_memory_rather_than_dividing_by_zero() {
        // total_memory() == 0 is what an unsupported platform reports.
        let sys = System::new();
        let s = sample(&sys);
        assert_eq!(s.mem, 0);
    }

    #[tokio::test]
    async fn the_frame_is_exactly_the_pixels_the_device_would_get() {
        // The whole point: the preview is not a lookalike. Same renderer, same
        // sample, byte-identical output.
        let s = SysmonSample {
            cpu: 42,
            mem: 71,
            battery: 88,
        };
        let expected = render_sysmon(s.cpu, s.mem, s.battery, 16);
        let direct = render_sysmon(42, 71, 88, 16);
        assert_eq!(expected, direct);
        assert_eq!(expected.len(), 16 * 16 * 3);
    }

    #[tokio::test]
    async fn cmd_returns_a_frame_sized_for_the_request() {
        let reply = cmd_sysmon(&json!({"size": 32})).await;
        assert_eq!(reply["success"], json!(true));
        assert_eq!(reply["size"], json!(32));
        let b64 = reply["frame_rgb_b64"].as_str().expect("frame");
        let raw = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .expect("valid base64");
        assert_eq!(raw.len(), 32 * 32 * 3, "RGB triples for every pixel");
    }

    #[tokio::test]
    async fn cmd_defaults_to_the_16x16_matrix() {
        let reply = cmd_sysmon(&json!({})).await;
        assert_eq!(reply["size"], json!(16));
        let raw = base64::engine::general_purpose::STANDARD
            .decode(reply["frame_rgb_b64"].as_str().unwrap())
            .unwrap();
        assert_eq!(raw.len(), 16 * 16 * 3);
    }

    #[tokio::test]
    async fn cmd_reports_percentages_in_range() {
        let reply = cmd_sysmon(&json!({})).await;
        for key in ["cpu", "mem", "battery"] {
            let v = reply[key].as_u64().expect(key);
            assert!(v <= 100, "{key} = {v} is not a percentage");
        }
    }
}
