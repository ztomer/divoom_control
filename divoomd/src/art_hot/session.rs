//! Device-driven BLE upload session for the hot channel. Pulled out of
//! `art_hot.rs` to keep both files under the 500-LOC ground rule.
//!
//! Session flow: send the 0x9B manifest, then loop on the device's 0xF7/0x9F
//! file requests — answer each with 0x9D file info, stream 0x9E packets, and
//! serve resend requests until the device confirms or goes quiet.

use super::{pick_file, HotFile, IDLE_DONE_TIMEOUT_SECS};
use crate::art::HotProgress;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};
use std::sync::Arc;

/// Opcodes of the session, named once.
const CMD_REQUEST: u8 = 0xF7;
const CMD_FILE_INFO: u8 = 0x9D;
const CMD_PACKET: u8 = 0x9E;
const CMD_DONE: u8 = 0x9F;

type Ble = crate::daemon::DeviceTransport;

fn idle_timeout() -> tokio::time::Duration {
    tokio::time::Duration::from_secs_f64(IDLE_DONE_TIMEOUT_SECS)
}

fn debug_on() -> bool {
    std::env::var("DIVOOMD_BLE_DEBUG").is_ok()
}

/// What the device said to a 0x9D file offer.
enum Offer {
    /// Accepted; stream from this packet index.
    Accepted { start_pkt: usize },
    /// Declined, or the ack was malformed: skip the file.
    Declined,
    /// Another 0xF7 request arrived instead of the ack: serve it next.
    Requested(Vec<u8>),
    /// Nothing within the idle timeout.
    Quiet,
}

/// How a streamed file ended.
enum Outcome {
    Confirmed,
    /// Confirmed, and the device's next request arrived with it.
    ConfirmedThen(Vec<u8>),
    Unconfirmed,
}

pub(super) async fn run_hot_session(
    ble: &Ble,
    files: &[HotFile],
    ok_dl: usize,
    progress: Arc<HotProgress>,
) -> Result<Value, String> {
    let dbg = debug_on();
    let vendors = send_manifest(ble, files).await?;
    if dbg {
        eprintln!("[hot] sent 0x9B manifest: {vendors} vendor(s), {ok_dl} files downloaded");
    }

    let mut served: Vec<Value> = Vec::new();
    let mut pending_request: Option<Vec<u8>> = None;
    loop {
        let (cmd, payload) = if let Some(p) = pending_request.take() {
            (CMD_REQUEST, p)
        } else if let Some(r) = ble
            .wait_for_any_response(&[CMD_REQUEST, CMD_DONE], idle_timeout())
            .await
        {
            r
        } else {
            if dbg {
                eprintln!("[hot] wait([f7,9f]) TIMED OUT after {IDLE_DONE_TIMEOUT_SECS}s -> ending (device quiet)");
            }
            break; // device quiet -- up to date
        };
        if cmd == CMD_DONE {
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
        let Some(f) = pick_file(files, vendor_id, version) else {
            if dbg {
                eprintln!("[hot] request vendor={vendor_id} v{version} -> pick_file NONE -> break (nothing to serve)");
            }
            break;
        };
        if dbg {
            eprintln!(
                "[hot] request vendor={vendor_id} v{version} -> pick_file MATCH {} v{}",
                f.file_id, f.version
            );
        }
        let start_pkt = match offer_file(ble, f).await? {
            Offer::Accepted { start_pkt } => start_pkt,
            Offer::Declined => continue,
            Offer::Requested(p) => {
                pending_request = Some(p);
                continue;
            }
            Offer::Quiet => break,
        };
        if dbg {
            eprintln!(
                "[hot] 0x9D accepted, streaming from packet {start_pkt} of {}",
                f.packet_count()
            );
        }
        stream_packets(ble, f, start_pkt).await;
        let confirmed = match serve_resends(ble, f).await {
            Outcome::Confirmed => true,
            Outcome::ConfirmedThen(p) => {
                pending_request = Some(p);
                true
            }
            Outcome::Unconfirmed => false,
        };
        served.push(json!({"file_id": &f.file_id, "version": f.version, "confirmed": confirmed}));
        let n_served = served.len();
        progress.set(
            &json!({"phase":"uploading","current":n_served,"total":ok_dl,"file_id":&f.file_id}),
        );
    }

    let confirmed_count = served
        .iter()
        .filter(|s| {
            s.get("confirmed")
                .and_then(serde_json::Value::as_bool)
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

/// The 0x9B manifest: `[count] + {vendorId:4 LE, newestVersion:4 LE}*` over
/// the files that have a body. Returns the vendor count.
async fn send_manifest(ble: &Ble, files: &[HotFile]) -> Result<usize, String> {
    let mut vendors: std::collections::HashMap<u32, u32> = std::collections::HashMap::new();
    for f in files.iter().filter(|f| !f.body.is_empty()) {
        let e = vendors.entry(f.vendor_id).or_insert(0);
        if f.version > *e {
            *e = f.version;
        }
    }
    let mut manifest_payload = vec![vendors.len().byte()];
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
    Ok(vendors.len())
}

/// Send the 0x9D file info and read the device's answer.
async fn offer_file(ble: &Ble, f: &HotFile) -> Result<Offer, String> {
    let dbg = debug_on();
    let mut info = Vec::new();
    info.extend_from_slice(&f.vendor_id.to_le_bytes());
    info.extend_from_slice(&(f.body.len().dword()).to_le_bytes());
    info.extend_from_slice(&f.checksum().to_le_bytes());
    info.extend_from_slice(&f.version.to_le_bytes());
    if ble.send_command(CMD_FILE_INFO, &info, true).await.is_err() {
        return Err("file info (0x9D) write failed".into());
    }
    let Some((cmd, ack)) = ble
        .wait_for_any_response(&[CMD_FILE_INFO, CMD_REQUEST], idle_timeout())
        .await
    else {
        if dbg {
            eprintln!("[hot] no 0x9D ack (timeout) -> break");
        }
        return Ok(Offer::Quiet);
    };
    if cmd == CMD_REQUEST {
        if dbg {
            eprintln!("[hot] 0x9D ack was another 0xF7 -> re-loop");
        }
        return Ok(Offer::Requested(ack));
    }
    if ack.is_empty() || ack[0] != 0 {
        if dbg {
            eprintln!("[hot] 0x9D ack declined (payload {ack:02x?}) -> skip file");
        }
        return Ok(Offer::Declined);
    }
    let start_pkt = if ack.len() >= 3 {
        usize::from(u16::from_le_bytes([ack[1], ack[2]]))
    } else {
        0
    };
    Ok(Offer::Accepted { start_pkt })
}

/// Stream the file's 0x9E packets from `start_pkt`; a failed write ends the
/// stream early (the resend phase can still recover it).
async fn stream_packets(ble: &Ble, f: &HotFile, start_pkt: usize) {
    for idx in start_pkt..f.packet_count() {
        let mut pkt_payload = Vec::new();
        pkt_payload.extend_from_slice(&(idx.word()).to_le_bytes());
        pkt_payload.extend_from_slice(&f.packet(idx));
        if ble
            .send_command(CMD_PACKET, &pkt_payload, true)
            .await
            .is_err()
        {
            break;
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(20)).await;
    }
}

/// After the stream: serve resend requests until the device confirms the
/// file, asks for the next one, or goes quiet.
async fn serve_resends(ble: &Ble, f: &HotFile) -> Outcome {
    loop {
        match ble
            .wait_for_any_response(&[CMD_PACKET, CMD_REQUEST], idle_timeout())
            .await
        {
            None => return Outcome::Unconfirmed, // IDLE_DONE_TIMEOUT -- unconfirmed
            Some((c, p)) if c == CMD_REQUEST => return Outcome::ConfirmedThen(p),
            Some((_, p)) if !p.is_empty() && (p[0] == 1 || p[0] == 2) => {
                return Outcome::Confirmed;
            }
            Some((_, p)) if p.len() >= 3 && p[0] == 0 => {
                let ridx = usize::from(u16::from_le_bytes([p[1], p[2]]));
                let mut rp = Vec::new();
                rp.extend_from_slice(&(ridx.word()).to_le_bytes());
                rp.extend_from_slice(&f.packet(ridx));
                let _ = ble.send_command(CMD_PACKET, &rp, true).await;
            }
            _ => {}
        }
    }
}
