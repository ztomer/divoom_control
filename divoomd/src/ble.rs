//! BLE transport (btleplug) — connect / notify / write against a real Divoom, on
//! the foundation the TCC spike proved. Wires the hardware-free ported modules
//! (`framing`, `response`, `autoprobe`) to a `Peripheral`.
//!
//! Feature-gated (`ble`) so the protocol core + its tests stay btleplug-free. This
//! module can't be unit-tested (it needs a device); its verification is over the
//! socket against a real Pixoo/Ditoo once the daemon `.app` holds the BT grant.

use std::time::Duration;

use btleplug::api::{
    CharPropFlags, Characteristic, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
use btleplug::platform::{Manager, Peripheral};

use crate::central::BleCentral;

/// The platform BLE adapter. On macOS the CoreBluetooth central manager it wraps
/// MUST stay alive for the duration of a connection — dropping it silently stops
/// notification delivery — so callers hold it (the daemon caches one; each
/// `BleTransport` keeps a clone).
pub use btleplug::platform::Adapter;
use tokio::sync::{mpsc, Mutex};
use uuid::Uuid;

use crate::autoprobe::Protocol;
use crate::framing;
use crate::response::{self, Frame};

mod connect;

// Divoom GATT (ISSC transparent-UART service), from divoom_lib/divoom.py.
const WRITE_UUID: Uuid = Uuid::from_u128(0x49535343_8841_43f4_a8d4_ecbe34729bb3);
const NOTIFY_UUID: Uuid = Uuid::from_u128(0x49535343_1e4d_4bd9_ba61_23c647249616);

const DEVICE_NAME_HINTS: &[&str] = &["Pixoo", "Divoom", "Tivoo", "Timoo", "Ditoo", "Timebox"];

/// Upper bound on a single BLE write. A write to a peripheral that vanished
/// (device powered off, out of range, or Bluetooth toggled mid-operation) can
/// otherwise hang forever — and since the write runs while the caller holds the
/// daemon's `device` lock, that wedges ALL device ops (and the device_status
/// liveness probe, which then falsely reports the daemon down). Bounding it lets
/// the op fail, release the lock, and the daemon self-recover.
const WRITE_TIMEOUT: Duration = Duration::from_secs(5);

/// Upper bound on each GATT setup step (connect / discover / subscribe).
/// CoreBluetooth's `connect()` waits INDEFINITELY for an unresponsive device
/// (off, out of range, or already connected elsewhere) — and the connect runs
/// while the daemon holds the `device` lock, so an unbounded hang wedges the
/// whole device path. Bounded so a bad connect fails and the caller can retry.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(20);

pub use crate::transport::BleResult;

/// A device discovered during a scan.
#[derive(Debug, Clone)]
pub struct Discovered {
    pub name: String,
    pub id: String,
}

/// Create the platform adapter. The caller must keep it alive (see [`Adapter`]).
pub async fn make_central() -> BleResult<BleCentral> {
    let manager = Manager::new().await?;
    let adapter =
        manager.adapters().await?.into_iter().next().ok_or_else(
            || -> Box<dyn std::error::Error + Send + Sync> { "no BLE adapter".into() },
        )?;
    Ok(BleCentral::Real(adapter))
}

/// Backstop cap for a scan window (mirrors the Python daemon's
/// `_SCAN_RESULT_TIMEOUT`): a long user-configured timeout must not run the
/// adapter for minutes.
const SCAN_TIMEOUT_CAP: Duration = Duration::from_secs(90);

/// Scan for Divoom devices for `timeout`, returning name + id pairs.
///
/// Deliberately a single scan window, then one `peripherals()` enumeration
/// AFTER `stop_scan`: on macOS/CoreBluetooth, querying peripheral `properties()`
/// while a scan is still active blocks and wedges the scan, so it must be read
/// only once the scan has stopped. A long user-configured timeout is capped at
/// `SCAN_TIMEOUT_CAP` (mirrors the Python daemon's `_SCAN_RESULT_TIMEOUT`) so a
/// stray large value can't run the adapter for minutes.
pub async fn scan(central: &BleCentral, timeout: Duration) -> BleResult<Vec<Discovered>> {
    let dur = timeout.min(SCAN_TIMEOUT_CAP);
    // Guard the whole scan in a timeout. A dead CoreBluetooth session (after a
    // disconnect / Bluetooth toggle) makes `start_scan`/`peripherals` hang
    // forever with no error — which would wedge the scan command and defeat the
    // caller's `reset_central` self-heal (it only fires on an `Err`). The timeout
    // turns the hang into an `Err` matching `is_dead_central` so the daemon
    // rebuilds the central and retries.
    let work = async {
        central.start_scan(ScanFilter::default()).await?;
        tokio::time::sleep(dur).await;
        central.stop_scan().await?;
        let mut out = Vec::new();
        for p in central.peripherals().await? {
            let name = p
                .properties()
                .await?
                .and_then(|pr| pr.local_name)
                .unwrap_or_default();
            if DEVICE_NAME_HINTS.iter().any(|h| name.contains(h)) {
                out.push(Discovered {
                    name,
                    id: p.id().to_string(),
                });
            }
        }
        Ok(out)
    };
    match tokio::time::timeout(dur + Duration::from_secs(10), work).await {
        Ok(r) => r,
        Err(_) => Err("scan timed out: central may be stale (Channel closed)".into()),
    }
}

/// An owned connection to one device: serialized writes + a parsed-frame channel.
pub struct BleTransport {
    // keep the central alive for the connection's lifetime (notifications need it)
    _central: BleCentral,
    peripheral: Peripheral,
    write_char: Characteristic,
    protocol: Protocol,
    rx: Mutex<mpsc::Receiver<Frame>>,
    device_name: std::sync::Mutex<Option<String>>,
}

impl BleTransport {
    /// Connect to the device whose `id` matches a prior `scan()` result. Discovers
    /// services, subscribes to notifications, spawns the frame-parsing task, and
    /// runs the autoprobe to pick the framing.
    pub async fn connect(central: &BleCentral, id: &str) -> BleResult<Self> {
        connect::connect(central, id).await
    }

    pub fn device_name(&self) -> Option<String> {
        self.device_name.lock().unwrap().clone()
    }

    pub fn set_cached_device_name(&self, name: String) {
        *self.device_name.lock().unwrap() = Some(name);
    }

    /// Detect the framing by probing 0x46 in iOS-LE then Basic (default Basic).
    /// Mirrors `autoprobe_protocol`. Sets `self.protocol`.
    async fn autoprobe(&mut self) {
        let probe = Duration::from_millis(1500);
        self.protocol = Protocol::IosLe;
        if self.send_command_and_wait(0x46, &[], probe).await.is_some() {
            return; // iOS-LE answered
        }
        self.protocol = Protocol::Basic;
        let _ = self.send_command_and_wait(0x46, &[], probe).await; // warm/confirm; Basic is the default
        self.protocol = Protocol::Basic;
    }

    pub fn protocol(&self) -> Protocol {
        self.protocol
    }

    pub fn set_protocol(&mut self, protocol: Protocol) {
        self.protocol = protocol;
    }

    /// Encode `[command_id, args...]` in the active framing and write it.
    pub async fn send_command(
        &self,
        command_id: u8,
        args: &[u8],
        write_with_response: bool,
    ) -> BleResult<()> {
        if std::env::var("DIVOOMD_BLE_DEBUG").is_ok() {
            let n = args.len().min(12);
            let hx: String = args[..n].iter().map(|b| format!("{b:02x}")).collect();
            eprintln!(
                "[ble] tx cmd=0x{command_id:02x} ({} args){}",
                args.len(),
                if n > 0 {
                    format!(" {hx}{}", if args.len() > n { ".." } else { "" })
                } else {
                    String::new()
                }
            );
        }
        let mut payload = Vec::with_capacity(1 + args.len());
        payload.push(command_id);
        payload.extend_from_slice(args);
        let frame = match self.protocol {
            Protocol::Basic => framing::encode_basic_payload(&payload, false),
            Protocol::IosLe => framing::encode_ios_le_payload(&payload, 0)?,
        };
        let wtype = if write_with_response {
            WriteType::WithResponse
        } else {
            WriteType::WithoutResponse
        };
        // prefer write-with-response only if the characteristic supports it
        let wtype = if matches!(wtype, WriteType::WithResponse)
            && !self.write_char.properties.contains(CharPropFlags::WRITE)
        {
            WriteType::WithoutResponse
        } else {
            wtype
        };
        match tokio::time::timeout(
            WRITE_TIMEOUT,
            self.peripheral.write(&self.write_char, &frame, wtype),
        )
        .await
        {
            Ok(res) => res?, // write finished (Ok, or a real BLE error to propagate)
            Err(_) => return Err("BLE write timed out (device unreachable)".into()),
        }
        Ok(())
    }

    /// Wait for the response to `command_id` (resolves on the exact id, skips the
    /// 0x33 generic-ACK), or `None` on timeout. Uses the ported correlation.
    pub async fn wait_for_response(&self, command_id: u8, timeout: Duration) -> Option<Vec<u8>> {
        let mut rx = self.rx.lock().await;
        response::wait_for_response(&mut rx, command_id, timeout).await
    }

    /// Drain → send → wait, mirroring `send_command_and_wait_for_response`. The
    /// device emits UNSOLICITED frames (e.g. a proactive 0x46 on a brightness
    /// change), so stale frames are dropped before the query to avoid reading a
    /// value one step behind (HW-confirmed in the Python impl).
    pub async fn send_command_and_wait(
        &self,
        command_id: u8,
        args: &[u8],
        timeout: Duration,
    ) -> Option<Vec<u8>> {
        {
            let mut rx = self.rx.lock().await;
            while rx.try_recv().is_ok() {}
        }
        self.send_command(command_id, args, true).await.ok()?;
        self.wait_for_response(command_id, timeout).await
    }

    /// Stream a pre-encoded animation blob via the 0x8B 3-phase protocol.
    /// Mirrors `stream_animation_8b` in `divoom_lib/display/animation.py`:
    ///
    ///   Phase 1 — START (CW=0): [0x00, file_size:4 LE]
    ///             wait for device "ready" reply (payload[0]==0); fall back to 0.5s sleep.
    ///   Phase 2 — DATA (CW=1):  [0x01, file_size:4 LE, offset_id:2 LE, chunk...]
    ///             256-byte chunks; MUST be 256 (APK/futpib hardcoded, device places
    ///             chunk N at byte N*256 — smaller chunks leave permanent gaps).
    ///   Phase 3 — RETRANSMIT:   device sends 0x8B [1, idx_lo, idx_hi]; re-send that chunk.
    ///             Stop when device is quiet for 1 s (normal end state).
    ///
    /// No TERMINATE (CW=2) packet — verified correct on 4 hardware devices.
    pub async fn stream_animation_8b(&self, blob: &[u8]) -> BleResult<bool> {
        const CMD: u8 = 0x8B;
        const CHUNK_SIZE: usize = 256;

        let file_size = blob.len() as u32;
        if file_size == 0 {
            return Ok(false);
        }

        // Phase 1: START — [CW=0, file_size:4 LE]
        let mut start_args = Vec::with_capacity(5);
        start_args.push(0u8);
        start_args.extend_from_slice(&file_size.to_le_bytes());
        self.send_command(CMD, &start_args, true).await?;

        // Wait for device "ready" ACK (payload[0]==0). Fall back to 0.5s sleep if no reply.
        let device_ready = {
            let mut rx = self.rx.lock().await;
            let deadline = std::time::Instant::now() + Duration::from_millis(2000);
            let mut ready = false;
            loop {
                let remaining = deadline.saturating_duration_since(std::time::Instant::now());
                if remaining.is_zero() {
                    break;
                }
                match tokio::time::timeout(remaining, rx.recv()).await {
                    Ok(Some(frame)) if frame.command_id == CMD => {
                        if frame.payload.first() == Some(&0) {
                            ready = true;
                            break;
                        }
                        // stale frame or early retransmit — keep waiting
                    }
                    _ => break,
                }
            }
            ready
        };
        if !device_ready {
            tokio::time::sleep(Duration::from_millis(500)).await;
        }

        // Phase 2: DATA chunks — [CW=1, file_size:4 LE, offset_id:2 LE, chunk...]
        let mut offset_id: u16 = 0;
        let mut pos = 0usize;
        while pos < blob.len() {
            let end = (pos + CHUNK_SIZE).min(blob.len());
            let chunk = &blob[pos..end];
            let mut args = Vec::with_capacity(7 + chunk.len());
            args.push(1u8); // CW=1 SENDING_DATA
            args.extend_from_slice(&file_size.to_le_bytes());
            args.extend_from_slice(&offset_id.to_le_bytes());
            args.extend_from_slice(chunk);
            self.send_command(CMD, &args, true).await?;
            offset_id += 1;
            pos += CHUNK_SIZE;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }

        // Phase 3: serve retransmit requests — device sends 0x8B [1, idx_lo, idx_hi].
        // Stop when quiet for 1 s (device has everything).
        for _ in 0..256usize {
            let frame = {
                let mut rx = self.rx.lock().await;
                match tokio::time::timeout(Duration::from_millis(1000), rx.recv()).await {
                    Ok(Some(f)) => f,
                    _ => break, // timeout = device quiet = done
                }
            };
            if frame.command_id != CMD {
                continue;
            }
            let p = &frame.payload;
            if p.len() >= 3 && p[0] == 1 {
                let idx = u16::from_le_bytes([p[1], p[2]]) as usize;
                let start = idx * CHUNK_SIZE;
                if start < blob.len() {
                    let chunk = &blob[start..(start + CHUNK_SIZE).min(blob.len())];
                    let mut args = Vec::with_capacity(7 + chunk.len());
                    args.push(1u8);
                    args.extend_from_slice(&file_size.to_le_bytes());
                    args.extend_from_slice(&(idx as u16).to_le_bytes());
                    args.extend_from_slice(chunk);
                    self.send_command(CMD, &args, true).await?;
                }
            }
            // payload[0]==0 (another start-ack) or unknown — ignore and keep listening
        }

        Ok(true)
    }

    /// Wait until a frame arrives whose command_id is one of `command_ids`.
    /// Returns `Some((command_id, payload))` or `None` on timeout.
    /// Frames with non-matching IDs are dropped (they were unsolicited broadcast frames).
    pub async fn wait_for_any_response(
        &self,
        command_ids: &[u8],
        timeout: Duration,
    ) -> Option<(u8, Vec<u8>)> {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                return None;
            }
            let frame = {
                let mut rx = self.rx.lock().await;
                match tokio::time::timeout(remaining, rx.recv()).await {
                    Ok(Some(f)) => f,
                    _ => return None,
                }
            };
            if command_ids.contains(&frame.command_id) {
                return Some((frame.command_id, frame.payload));
            }
        }
    }

    pub async fn disconnect(&self) -> BleResult<()> {
        self.peripheral.disconnect().await?;
        Ok(())
    }
}
