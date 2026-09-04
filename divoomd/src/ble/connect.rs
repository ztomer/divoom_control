//! GATT setup for a single device (discovery, connect, subscribe, framing-task
//! spawn). Pulled out of ble.rs to keep both files under the 500-LOC rule.

use btleplug::api::{Peripheral as _, ScanFilter};
use futures::StreamExt;
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, Mutex};

use super::{BleCentral, BleResult, BleTransport, CONNECT_TIMEOUT};
use crate::autoprobe::Protocol;
use crate::framing;
use crate::models::IOS_LE_HEADER;
use crate::response::Frame;

/// Connect to the device whose `id` matches a prior `scan()` result. Discovers
/// services, subscribes to notifications, spawns the frame-parsing task, and
/// runs the autoprobe to pick the framing.
pub(super) async fn connect(central: &BleCentral, id: &str) -> BleResult<BleTransport> {
    // Ensure the peripheral is known to the adapter. A single fixed scan window
    // intermittently misses a device on macOS (its next advertisement may not
    // land inside the window) — most visibly on RECONNECT after a disconnect.
    // Poll the discovered set until the target appears or a deadline passes,
    // mirroring the Python daemon's reconnect-scan retries.
    let _dbg = std::env::var("DIVOOMD_BLE_DEBUG").is_ok();
    if _dbg {
        eprintln!("[ble][connect] start_scan");
    }
    // EVERY central await below is bounded by a timeout. On a dead
    // CoreBluetooth session `start_scan`/`peripherals`/`stop_scan` hang forever
    // with no error, which would wedge `connect` and defeat the caller's
    // `reset_central` self-heal (it only fires on an `Err`). Each timeout turns
    // the hang into an `Err` matching `is_dead_central`, so the daemon rebuilds
    // the central + retries instead of hanging.
    match tokio::time::timeout(
        Duration::from_secs(5),
        central.start_scan(ScanFilter::default()),
    )
    .await
    {
        Ok(r) => r?,
        Err(_) => {
            return Err("BLE scan start timed out: central may be stale (Channel closed)".into())
        }
    }
    let deadline = Instant::now() + Duration::from_secs(8);
    let mut found = None;
    while Instant::now() < deadline {
        match tokio::time::timeout(Duration::from_secs(2), central.peripherals()).await {
            Ok(peripherals) => {
                // R67: case-INSENSITIVE. This was `==`, and it made the virtual
                // wall impossible to connect on macOS: `wall_configure`
                // uppercases its slot keys (a convention that fits real MAC
                // addresses like AA:BB:CC), while macOS identifies peripherals
                // by a LOWERCASE UUID. The uppercased id therefore matched
                // nothing and every slot failed with "All wall slots failed to
                // connect" — for a device that had just been found by a scan.
                //
                // Fixed at the matching site rather than at the one caller, so
                // no future caller has to know the casing convention.
                if let Some(p) = peripherals?
                    .into_iter()
                    .find(|p| p.id().to_string().eq_ignore_ascii_case(id))
                {
                    found = Some(p);
                    break;
                }
            }
            Err(_) => {
                let _ = tokio::time::timeout(Duration::from_secs(3), central.stop_scan()).await;
                return Err(
                    "BLE discovery timed out: central may be stale (Channel closed)".into(),
                );
            }
        }
        tokio::time::sleep(Duration::from_millis(400)).await;
    }
    let _ = tokio::time::timeout(Duration::from_secs(3), central.stop_scan()).await;
    let peripheral = found.ok_or_else(|| "device not found in scan".to_string())?;
    if _dbg {
        eprintln!("[ble][connect] found peripheral, connecting");
    }

    // NOTE (Linux/BlueZ): these dual-mode Divoom devices also advertise the
    // classic SPP profile (UUID 0x1101), and BlueZ routes connect() to BR/EDR —
    // returning org.bluez.Error.BREDR.ProfileUnavailable ("No more profiles to
    // connect to") or a D-Bus "Timeout waiting for reply", even though the LE
    // GATT link briefly comes up. CoreBluetooth (macOS) connects fine. Making
    // BLE connect reliable on Linux needs forcing the LE transport / pairing /
    // disabling BR/EDR — tracked in scripts/linux_remote/README.md. Scan works
    // on Linux today; connect does not.
    match tokio::time::timeout(CONNECT_TIMEOUT, peripheral.connect()).await {
        Ok(r) => {
            if _dbg {
                eprintln!("[ble][connect] connect returned");
            }
            r?;
        }
        Err(_) => return Err("BLE connect timed out".into()),
    }
    if _dbg {
        eprintln!("[ble][connect] discover_services");
    }
    match tokio::time::timeout(CONNECT_TIMEOUT, peripheral.discover_services()).await {
        Ok(r) => r?,
        Err(_) => return Err("BLE discover_services timed out".into()),
    }
    let chars = peripheral.characteristics();
    let write_char = chars
        .iter()
        .find(|c| c.uuid == super::WRITE_UUID)
        .ok_or("no write characteristic")?
        .clone();
    let notify_char = chars
        .iter()
        .find(|c| c.uuid == super::NOTIFY_UUID)
        .ok_or("no notify characteristic")?
        .clone();

    match tokio::time::timeout(CONNECT_TIMEOUT, peripheral.subscribe(&notify_char)).await {
        Ok(r) => r?,
        Err(_) => return Err("BLE subscribe timed out".into()),
    }
    let mut notifications = peripheral.notifications().await?;
    let (tx, rx) = mpsc::channel::<Frame>(256);

    // Parse inbound bytes into Frames using the ported framing: iOS-LE frames
    // are self-delimited (header-prefixed); Basic frames need a stateful buffer.
    tokio::spawn(async move {
        let mut basic_buf: Vec<u8> = Vec::new();
        while let Some(n) = notifications.next().await {
            let data = n.value;
            if std::env::var("DIVOOMD_BLE_DEBUG").is_ok() {
                let hx: String = data.iter().map(|b| format!("{b:02x}")).collect();
                eprintln!("[ble] rx {} bytes: {hx}", data.len());
            }
            if data.len() >= 4 && data[0..4] == IOS_LE_HEADER {
                if let Some(p) = framing::parse_ios_le_notification(&data) {
                    if tx
                        .send(Frame {
                            command_id: p.command_id,
                            payload: p.payload,
                        })
                        .await
                        .is_err()
                    {
                        break;
                    }
                }
            } else {
                basic_buf.extend_from_slice(&data);
                for m in framing::parse_basic_protocol_frames(&mut basic_buf) {
                    if std::env::var("DIVOOMD_BLE_DEBUG").is_ok() {
                        eprintln!(
                            "[ble] basic frame cmd=0x{:02x} ({} payload bytes)",
                            m.command_id,
                            m.payload.len()
                        );
                    }
                    if tx
                        .send(Frame {
                            command_id: m.command_id,
                            payload: m.payload,
                        })
                        .await
                        .is_err()
                    {
                        return;
                    }
                }
            }
        }
    });

    let dev_name = peripheral
        .properties()
        .await
        .ok()
        .flatten()
        .and_then(|pr| pr.local_name);

    let mut transport = BleTransport {
        _central: central.clone(),
        peripheral,
        write_char,
        protocol: Protocol::Basic,
        rx: Mutex::new(rx),
        device_name: std::sync::Mutex::new(dev_name),
    };
    transport.autoprobe().await;
    Ok(transport)
}
