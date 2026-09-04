//! BLE central lifecycle for the daemon (split out of `daemon.rs` for the
//! 500-LOC house rule). Owns lazy (re)creation + reset of the shared
//! CoreBluetooth central and scan cleanup on shutdown.
use btleplug::api::Central;

use crate::ble;
use crate::central::BleCentral;
use crate::daemon::Daemon;

impl Daemon {
    /// Get (creating + caching once) the shared CoreBluetooth central.
    #[cfg(feature = "ble")]
    pub(crate) async fn central(&self) -> Result<BleCentral, String> {
        let mut g = self.central.lock().await;
        if g.is_none() {
            *g = Some(ble::make_central().await.map_err(|e| e.to_string())?);
        }
        Ok(g.as_ref().unwrap().clone())
    }

    /// Drop the cached central so the next `central()` recreates it. btleplug
    /// reports a dead CoreBluetooth session as "Channel closed" (the session ends
    /// after a device disconnect or a Bluetooth toggle); the stale Adapter can't
    /// recover, so every scan/connect fails until it's rebuilt. This lets the
    /// daemon self-heal without a restart.
    #[cfg(feature = "ble")]
    pub(crate) async fn reset_central(&self) {
        *self.central.lock().await = None;
    }

    /// On shutdown, stop any BLE scan still running on the cached central so we
    /// don't leave a leaked scan session with bluetoothd. Left uncleaned across
    /// rapid restarts, those stale sessions trip the OS scan-frequency throttle
    /// (scans then silently return 0 devices until Bluetooth is toggled).
    #[cfg(feature = "ble")]
    pub async fn stop_scan_cleanup(&self) {
        if let Some(BleCentral::Real(adapter)) = self.central.lock().await.as_ref() {
            let _ = adapter.stop_scan().await;
        }
    }
}
