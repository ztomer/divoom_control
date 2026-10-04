//! The BLE central, abstracted so tests can inject the two failure shapes a
//! real central actually produces.
//!
//! In production `BleCentral::Real` wraps btleplug's `Adapter`. Under
//! `#[cfg(test)]` two doubles exist, because btleplug has TWO distinct failure
//! modes and testing only one of them is how a behaviour change slips through
//! unnoticed (see the `tests` module below):
//!
//!   `Faulty`         never resolves — a genuinely wedged `CoreBluetooth`
//!                    session, so callers MUST wrap it in `tokio::time::timeout`.
//!   `PromptError(m)`  fails immediately with `m`.
//!
//! The second one exists because btleplug 0.13 changed real behaviour here. In
//! 0.12, several operations on a vanished peripheral or service had no reply
//! branch at all and simply HUNG, so the daemon's timeout guard was what turned
//! them into an error. 0.13 replies promptly instead — `discover_services` on
//! an unknown peripheral is now `RuntimeError("Peripheral no longer available")`
//! rather than a 20-second hang. That is strictly better for latency, but it
//! changes which text the daemon sees, and the daemon classifies faults by text.

use btleplug::api::Central;
use btleplug::platform::{Adapter, Peripheral};

use crate::transport::BleResult;

#[derive(Clone)]
pub enum BleCentral {
    Real(Adapter),
    #[cfg(test)]
    Faulty,
    /// Fails immediately with the given message instead of hanging. Models the
    /// prompt-error family btleplug 0.13 introduced (see the module docs).
    #[cfg(test)]
    PromptError(&'static str),
}

impl BleCentral {
    /// Begin a scan. On `Faulty` this never resolves (a wedged `CoreBluetooth`
    /// session) so callers MUST wrap it in `tokio::time::timeout`.
    ///
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn start_scan(&self, filter: btleplug::api::ScanFilter) -> BleResult<()> {
        match self {
            Self::Real(a) => a.start_scan(filter).await.map_err(std::convert::Into::into),
            #[cfg(test)]
            Self::Faulty => std::future::pending().await,
            #[cfg(test)]
            Self::PromptError(m) => Err(m.to_owned().into()),
        }
    }

    /// Enumerate discovered peripherals. Same wedge contract as `start_scan`.
    ///
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn peripherals(&self) -> BleResult<Vec<Peripheral>> {
        match self {
            Self::Real(a) => a.peripherals().await.map_err(std::convert::Into::into),
            #[cfg(test)]
            Self::Faulty => std::future::pending().await,
            #[cfg(test)]
            Self::PromptError(m) => Err(m.to_owned().into()),
        }
    }

    /// Stop a scan (best-effort; the caller ignores a wedged stop).
    ///
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn stop_scan(&self) -> BleResult<()> {
        match self {
            Self::Real(a) => a.stop_scan().await.map_err(std::convert::Into::into),
            #[cfg(test)]
            Self::Faulty => std::future::pending().await,
            #[cfg(test)]
            Self::PromptError(m) => Err(m.to_owned().into()),
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

    /// Pins the behaviour CHANGE that btleplug 0.13 brings, in both directions.
    ///
    /// The existing tests above assert only on `is_dead_central`'s INPUTS, so
    /// they would stay green while the set of errors reaching it narrowed. That
    /// is the differential-blindness trap: a comparison against strings the code
    /// itself supplies cannot see a change in which strings arrive. So this goes
    /// through the real seam instead — a `BleCentral` that fails the way 0.13
    /// actually fails — and asserts what the daemon then does.
    #[tokio::test]
    async fn prompt_runtime_errors_are_not_central_faults() {
        // 0.12 HUNG here and our 20s guard turned it into "...central may be
        // stale", which matched, so the central was rebuilt and the scan
        // retried. 0.13 answers immediately with this instead.
        let c = BleCentral::PromptError("Runtime Error: Peripheral no longer available");

        let r = timeout(
            Duration::from_secs(20),
            ble::scan(&c, Duration::from_secs(2)),
        )
        .await;
        assert!(r.is_ok(), "0.13 answers promptly; it must not hang");
        let err = r
            .unwrap()
            .expect_err("PromptError central must fail the scan");

        // Assert the narrowing is a DECISION. If a future btleplug rewords this
        // so it starts matching again, or if someone adds "Runtime Error" to
        // `is_dead_central` to "restore" the old retry count, this goes red.
        assert!(
            !is_dead_central(&err.to_string()),
            "a vanished peripheral is not a dead central; rebuilding it cannot \
             help, so this must NOT be classified as one"
        );
    }

    /// The other half: the case the self-heal was built for must STILL heal.
    /// btleplug's `From<SendError>` renders "Channel closed" verbatim in 0.13,
    /// but that is an upstream rendering detail, so it is asserted rather than
    /// assumed — and asserting the exact text is what makes the first test's
    /// `!is_dead_central` meaningful rather than vacuous.
    #[tokio::test]
    async fn a_genuinely_dead_central_still_heals() {
        let c = BleCentral::PromptError("Channel closed");
        let err = ble::scan(&c, Duration::from_secs(2))
            .await
            .expect_err("must fail");
        assert!(
            is_dead_central(&err.to_string()),
            "a dead CoreBluetooth session must still trigger reset_central + retry"
        );
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
