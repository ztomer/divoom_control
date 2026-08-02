//! Device-driven BLE upload session for the hot channel. Pulled out of
//! art_hot.rs to keep both files under the 500-LOC ground rule.
//!
//! Session flow: send the 0x9B manifest, then loop on the device's 0xF7/0x9F
//! file requests — answer each with 0x9D file info, stream 0x9E packets, and
//! serve resend requests until the device confirms or goes quiet.

use super::{pick_file, HotFile, IDLE_DONE_TIMEOUT_SECS};
use crate::art::HotProgress;
use serde_json::{json, Value};
use std::sync::Arc;

pub(super) async fn run_hot_session(
    ble: &crate::daemon::DeviceTransport,
    files: &[HotFile],
    ok_dl: usize,
    progress: Arc<HotProgress>,
) -> Result<Value, String> {
    use tokio::time::Duration;

    // Build 0x9B manifest payload: [count] + {vendorId:4 LE, newestVersion:4 LE}*
    let mut vendors: std::collections::HashMap<u32, u32> = std::collections::HashMap::new();
    for f in files.iter().filter(|f| !f.body.is_empty()) {
        let e = vendors.entry(f.vendor_id).or_insert(0);
        if f.version > *e {
            *e = f.version;
        }
    }
    let mut manifest_payload = vec![vendors.len() as u8];
    for (vid, newest) in &vendors {
        manifest_payload.extend_from_slice(&vid.to_le_bytes());
        manifest_payload.extend_from_slice(&newest.to_le_bytes());
    }
    if ble
        .send_command(0x9B, &manifest_payload, true)
        .await
        .is_err()
    {
        return Err("manifest (0x9B) write failed".into());
    }

    let cmd_f7: u8 = 0xF7;
    let cmd_9d: u8 = 0x9D;
    let cmd_9e: u8 = 0x9E;
    let cmd_9f: u8 = 0x9F;
    let idle_to = Duration::from_secs_f64(IDLE_DONE_TIMEOUT_SECS);
    let mut served: Vec<Value> = Vec::new();
    let mut pending_request: Option<Vec<u8>> = None;
    let dbg = std::env::var("DIVOOMD_BLE_DEBUG").is_ok();
    if dbg {
        eprintln!(
            "[hot] sent 0x9B manifest: {} vendor(s), {} files downloaded",
            vendors.len(),
            ok_dl
        );
    }

    loop {
        let (cmd, payload) = if let Some(p) = pending_request.take() {
            (cmd_f7, p)
        } else {
            match ble.wait_for_any_response(&[cmd_f7, cmd_9f], idle_to).await {
                Some((c, p)) => (c, p),
                None => {
                    if dbg {
                        eprintln!("[hot] wait([f7,9f]) TIMED OUT after {IDLE_DONE_TIMEOUT_SECS}s -> ending (device quiet)");
                    }
                    break;
                } // device quiet — up to date
            }
        };
        if cmd == cmd_9f {
            if dbg {
                eprintln!("[hot] got 0x9F (pause) -> break");
            }
            break;
        }
        if payload.len() < 8 {
            if dbg {
                eprintln!(
                    "[hot] got 0x{cmd:02x} short payload len={} -> skip",
                    payload.len()
                );
            }
            continue;
        }
        let vendor_id = u32::from_le_bytes(payload[0..4].try_into().unwrap_or([0; 4]));
        let version = u32::from_le_bytes(payload[4..8].try_into().unwrap_or([0; 4]));
        let f = match pick_file(files, vendor_id, version) {
            Some(f) => {
                if dbg {
                    eprintln!(
                        "[hot] request vendor={vendor_id} v{version} -> pick_file MATCH {} v{}",
                        f.file_id, f.version
                    );
                }
                f
            }
            None => {
                if dbg {
                    eprintln!("[hot] request vendor={vendor_id} v{version} -> pick_file NONE -> break (nothing to serve)");
                }
                break;
            }
        };
        // Send 0x9D file info
        let mut info = Vec::new();
        info.extend_from_slice(&f.vendor_id.to_le_bytes());
        info.extend_from_slice(&(f.body.len() as u32).to_le_bytes());
        info.extend_from_slice(&f.checksum().to_le_bytes());
        info.extend_from_slice(&f.version.to_le_bytes());
        if ble.send_command(cmd_9d, &info, true).await.is_err() {
            return Err("file info (0x9D) write failed".into());
        }
        // Wait for 0x9D ack
        let ack = match ble.wait_for_any_response(&[cmd_9d, cmd_f7], idle_to).await {
            Some(a) => a,
            None => {
                if dbg {
                    eprintln!("[hot] no 0x9D ack (timeout) -> break");
                }
                break;
            }
        };
        if ack.0 == cmd_f7 {
            if dbg {
                eprintln!("[hot] 0x9D ack was another 0xF7 -> re-loop");
            }
            pending_request = Some(ack.1);
            continue;
        }
        let p2 = &ack.1;
        if p2.is_empty() || p2[0] != 0 {
            if dbg {
                eprintln!("[hot] 0x9D ack declined (payload {:02x?}) -> skip file", p2);
            }
            continue;
        }
        let start_pkt = if p2.len() >= 3 {
            u16::from_le_bytes([p2[1], p2[2]]) as usize
        } else {
            0
        };
        if dbg {
            eprintln!(
                "[hot] 0x9D accepted, streaming from packet {start_pkt} of {}",
                f.packet_count()
            );
        }

        // Stream file packets
        let total = f.packet_count();
        let mut confirmed = false;
        for idx in start_pkt..total {
            let mut pkt_payload = Vec::new();
            pkt_payload.extend_from_slice(&(idx as u16).to_le_bytes());
            pkt_payload.extend_from_slice(&f.packet(idx));
            if ble.send_command(cmd_9e, &pkt_payload, true).await.is_err() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        // Post-stream: serve resends until device declares done
        loop {
            match ble.wait_for_any_response(&[cmd_9e, cmd_f7], idle_to).await {
                None => break, // IDLE_DONE_TIMEOUT — unconfirmed
                Some((c, p)) if c == cmd_f7 => {
                    pending_request = Some(p);
                    confirmed = true;
                    break;
                }
                Some((_, p)) if !p.is_empty() && (p[0] == 1 || p[0] == 2) => {
                    confirmed = true;
                    break;
                }
                Some((_, p)) if p.len() >= 3 && p[0] == 0 => {
                    let ridx = u16::from_le_bytes([p[1], p[2]]) as usize;
                    let mut rp = Vec::new();
                    rp.extend_from_slice(&(ridx as u16).to_le_bytes());
                    rp.extend_from_slice(&f.packet(ridx));
                    let _ = ble.send_command(cmd_9e, &rp, true).await;
                }
                _ => {}
            }
        }
        served.push(json!({"file_id": &f.file_id, "version": f.version, "confirmed": confirmed}));
        let n_served = served.len();
        progress.set(
            json!({"phase":"uploading","current":n_served,"total":ok_dl,"file_id":&f.file_id}),
        );
    }

    let confirmed_count = served
        .iter()
        .filter(|s| {
            s.get("confirmed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        })
        .count();
    Ok(json!({
        "success": true,
        "served": served,
        "manifest": files.len(),
        "downloaded": ok_dl,
        "confirmed": confirmed_count,
    }))
}
