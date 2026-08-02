//! The BLE central, abstracted so tests can inject a *wedged* central.
//!
//! In production `BleCentral::Real` wraps btleplug's `Adapter`. Under `#[cfg(test)]`
//! a `Faulty` variant exists whose `start_scan`/`peripherals`/`stop_scan` never
//! resolve — letting the wedge + self-heal logic be exercised deterministically
//! without real Bluetooth hardware (see the `tests` module below).

use btleplug::api::Central;
use btleplug::platform::{Adapter, Peripheral};

use crate::transport::BleResult;

#[derive(Clone)]
pub enum BleCentral {
    Real(Adapter),
    #[cfg(test)]
    Faulty,
}

impl BleCentral {
    /// Begin a scan. On `Faulty` this never resolves (a wedged CoreBluetooth
    /// session) so callers MUST wrap it in `tokio::time::timeout`.
    pub async fn start_scan(&self, filter: btleplug::api::ScanFilter) -> BleResult<()> {
        match self {
            BleCentral::Real(a) => a.start_scan(filter).await.map_err(|e| e.into()),
            #[cfg(test)]
            BleCentral::Faulty => std::future::pending().await,
        }
    }

    /// Enumerate discovered peripherals. Same wedge contract as `start_scan`.
    pub async fn peripherals(&self) -> BleResult<Vec<Peripheral>> {
        match self {
            BleCentral::Real(a) => a.peripherals().await.map_err(|e| e.into()),
            #[cfg(test)]
            BleCentral::Faulty => std::future::pending().await,
        }
    }

    /// Stop a scan (best-effort; the caller ignores a wedged stop).
    pub async fn stop_scan(&self) -> BleResult<()> {
        match self {
            BleCentral::Real(a) => a.stop_scan().await.map_err(|e| e.into()),
            #[cfg(test)]
            BleCentral::Faulty => std::future::pending().await,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    use crate::ble;
    use crate::daemon_connect::is_dead_central;
    use tokio::time::timeout;

    #[test]
    fn is_dead_central_matches_wedge_and_channel_closed() {
        assert!(is_dead_central("connect failed: Channel closed"));
        assert!(is_dead_central(
            "scan timed out: central may be stale (Channel closed)"
        ));
        assert!(is_dead_central(
            "BLE discovery timed out: central may be stale (Channel closed)"
        ));
        assert!(is_dead_central(
            "BLE scan start timed out: central may be stale (Channel closed)"
        ));
    }

    #[test]
    fn is_dead_central_rejects_absent_device_and_no_adapter() {
        // These are honest "device not there" / config errors, NOT a dead
        // central — retrying via reset_central would be wrong.
        assert!(!is_dead_central("device not found in scan"));
        assert!(!is_dead_central("no BLE adapter"));
    }

    #[tokio::test]
    async fn scan_on_wedged_central_returns_within_bounds() {
        let c = BleCentral::Faulty;
        // Without the timeout guard this would hang forever. Assert it returns
        // and errors instead.
        let r = timeout(
            Duration::from_secs(20),
            ble::scan(&c, Duration::from_secs(2)),
        )
        .await;
        assert!(r.is_ok(), "scan must not hang on a wedged central");
        let res = r.unwrap();
        assert!(res.is_err(), "wedged scan should error");
        assert!(is_dead_central(&res.err().unwrap().to_string()));
    }

    #[tokio::test]
    async fn connect_on_wedged_central_returns_within_bounds() {
        let c = BleCentral::Faulty;
        let r = timeout(
            Duration::from_secs(30),
            ble::BleTransport::connect(&c, "any-id"),
        )
        .await;
        assert!(r.is_ok(), "connect must not hang on a wedged central");
        let res = r.unwrap();
        assert!(res.is_err(), "wedged connect should error");
        assert!(is_dead_central(&res.err().unwrap().to_string()));
    }
}
