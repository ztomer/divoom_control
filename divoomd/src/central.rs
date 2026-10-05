//! The BLE central, abstracted so tests can inject the failure shapes a real
//! central actually produces.
//!
//! In production `BleCentral::Real` wraps btleplug's `Adapter`. Under
//! `#[cfg(test)]` three doubles exist, because btleplug has THREE distinct
//! failure modes and testing only one of them is how a behaviour change slips
//! through unnoticed (see the `tests` module below):
//!
//!   `Faulty`         never resolves — a genuinely wedged `CoreBluetooth`
//!                    session, so callers MUST wrap it in `tokio::time::timeout`.
//!   `PromptError(m)`  fails immediately with `btleplug::Error::RuntimeError(m)`.
//!   `ChannelClosed`   fails immediately the way btleplug's macOS backend reports
//!                    a dead session, so the self-heal can be exercised without
//!                    a device.
//!
//! Every method converts its error through [`BleError::from_btle`] because this
//! is where `btleplug::Error` is still the CONCRETE type — the `BleResult` alias
//! erases it one `?` later. That is deliberate: the doubles inject `btleplug`
//! ERRORS, not strings, so the tests below assert what the daemon does with the
//! dependency's own variants rather than with prose the tests wrote themselves.
//!
//! The `PromptError` double exists because btleplug 0.13 changed real behaviour
//! here. In 0.12, several operations on a vanished peripheral or service had no
//! reply branch at all and simply HUNG, so the daemon's timeout guard was what
//! turned them into an error. 0.13 replies promptly instead — `discover_services`
//! on an unknown peripheral is now `RuntimeError("Peripheral no longer
//! available")` rather than a 20-second hang. That is strictly better for
//! latency, but it changes which fault the daemon classifies, and the daemon used
//! to classify faults by the text of the error.

use btleplug::api::Central;
use btleplug::platform::{Adapter, Peripheral};

use crate::ble_fault::BleError;

#[derive(Clone)]
pub enum BleCentral {
    Real(Adapter),
    #[cfg(test)]
    Faulty,
    /// Fails immediately with `btleplug::Error::RuntimeError(m)`. Models the
    /// prompt-error family btleplug 0.13 introduced (see the module docs).
    #[cfg(test)]
    PromptError(&'static str),
    /// Fails immediately the way btleplug's macOS backend reports a dead
    /// `CoreBluetooth` session. Its own variant rather than folded into
    /// `PromptError` because the two must classify DIFFERENTLY, which is the
    /// whole point of having both.
    #[cfg(test)]
    ChannelClosed,
}

impl BleCentral {
    /// Begin a scan. On `Faulty` this never resolves (a wedged `CoreBluetooth`
    /// session) so callers MUST wrap it in `tokio::time::timeout`.
    ///
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn start_scan(&self, filter: btleplug::api::ScanFilter) -> Result<(), BleError> {
        match self {
            Self::Real(a) => a
                .start_scan(filter)
                .await
                .map_err(|e| BleError::from_btle(&e)),
            #[cfg(test)]
            Self::Faulty => std::future::pending().await,
            #[cfg(test)]
            Self::PromptError(m) => Err(prompt_error(m)),
            #[cfg(test)]
            Self::ChannelClosed => Err(channel_closed()),
        }
    }

    /// Enumerate discovered peripherals. Same wedge contract as `start_scan`.
    ///
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn peripherals(&self) -> Result<Vec<Peripheral>, BleError> {
        match self {
            Self::Real(a) => a.peripherals().await.map_err(|e| BleError::from_btle(&e)),
            #[cfg(test)]
            Self::Faulty => std::future::pending().await,
            #[cfg(test)]
            Self::PromptError(m) => Err(prompt_error(m)),
            #[cfg(test)]
            Self::ChannelClosed => Err(channel_closed()),
        }
    }

    /// Stop a scan (best-effort; the caller ignores a wedged stop).
    ///
    /// # Errors
    ///
    /// From the BLE stack below: the adapter is gone, the peripheral is not
    /// connected, or the write did not complete.
    pub async fn stop_scan(&self) -> Result<(), BleError> {
        match self {
            Self::Real(a) => a.stop_scan().await.map_err(|e| BleError::from_btle(&e)),
            #[cfg(test)]
            Self::Faulty => std::future::pending().await,
            #[cfg(test)]
            Self::PromptError(m) => Err(prompt_error(m)),
            #[cfg(test)]
            Self::ChannelClosed => Err(channel_closed()),
        }
    }
}

/// The exact `btleplug::Error` 0.13 produces for a vanished peripheral, so the
/// tests below assert against the dependency's variant instead of a string they
/// invented and then pinned.
#[cfg(test)]
fn prompt_error(message: &'static str) -> BleError {
    let err = btleplug::Error::RuntimeError(message.to_owned());
    BleError::from_btle(&err)
}

/// The dead-session shape. `ble_fault`'s
/// `the_shape_btleplug_actually_produces_is_still_recognised` builds this same
/// value through btleplug's own macOS conversion and asserts it still reads
/// "Channel closed", so the two cannot drift apart unnoticed.
#[cfg(test)]
fn channel_closed() -> BleError {
    let err = btleplug::Error::Other("Channel closed".into());
    BleError::from_btle(&err)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    use crate::ble;
    use crate::ble_fault::BleFault;
    use crate::daemon_connect::is_dead_central;
    use tokio::time::timeout;

    /// Our own timeout guards: each says in its TYPE that the central is gone,
    /// so rewording the message cannot disarm the self-heal. What used to be
    /// four substring probes is now four constructor calls.
    #[test]
    fn our_own_timeout_guards_are_dead_central_faults() {
        for msg in [
            "scan timed out: central may be stale (Channel closed)",
            "BLE scan start timed out: central may be stale (Channel closed)",
            "BLE discovery timed out: central may be stale (Channel closed)",
            "BLE connect timed out",
            "BLE discover_services timed out",
            "BLE subscribe timed out",
        ] {
            assert!(is_dead_central(&BleError::dead_central(msg)), "{msg}");
        }
    }

    /// The honest "there is nothing here" / config failures, NOT a dead central:
    /// retrying via `reset_central` would be wrong.
    #[test]
    fn absent_device_and_no_adapter_are_not_central_faults() {
        for msg in ["device not found in scan", "no BLE adapter"] {
            assert!(!is_dead_central(&BleError::other(msg)), "{msg}");
        }
        for err in [
            btleplug::Error::DeviceNotFound,
            btleplug::Error::NoAdapterAvailable,
        ] {
            assert!(!is_dead_central(&BleError::from_btle(&err)), "{err:?}");
        }
    }

    /// Pins the behaviour CHANGE that btleplug 0.13 brings, in both directions.
    ///
    /// The tests above assert only on the classifier's INPUTS, so they would stay
    /// green while the set of errors reaching it narrowed. That is the
    /// differential-blindness trap: a comparison against errors the code itself
    /// supplies cannot see a change in which errors arrive. So this goes through
    /// the real seam instead — a `BleCentral` that fails the way 0.13 actually
    /// fails, with a real `btleplug::Error` inside — and asserts what the daemon
    /// then does.
    #[tokio::test]
    async fn prompt_runtime_errors_are_not_central_faults() {
        // 0.12 HUNG here and our 20s guard turned it into "...central may be
        // stale", which matched, so the central was rebuilt and the scan
        // retried. 0.13 answers immediately with this instead.
        let c = BleCentral::PromptError("Peripheral no longer available");

        let r = timeout(
            Duration::from_secs(20),
            ble::scan(&c, Duration::from_secs(2)),
        )
        .await;
        assert!(r.is_ok(), "0.13 answers promptly; it must not hang");
        let err = r
            .unwrap()
            .expect_err("PromptError central must fail the scan");

        // Assert the narrowing is a DECISION. If a future btleplug moves this
        // fault into another variant, or if someone adds the variant back to the
        // dead-central arm to "restore" the old retry count, this goes red.
        assert_eq!(
            err.fault(),
            BleFault::Other,
            "a vanished peripheral is not a dead central; rebuilding it cannot \
             help, so this must NOT be classified as one"
        );
        // AND the error really is 0.13's variant, not something the test could
        // have got wrong by construction: this is what decides the verdict.
        assert!(matches!(
            err.text(),
            "Runtime Error: Peripheral no longer available"
        ));
    }

    /// The other half: the case the self-heal was built for must STILL heal.
    /// btleplug's macOS `From<SendError>` produces this shape today, but that is
    /// an upstream rendering detail — `ble_fault`'s test builds it through
    /// btleplug's own conversion so a reword goes red instead of quiet. Asserting
    /// both halves here is what makes the test above's `BleFault::Other` a real
    /// decision rather than a classifier that answers `Other` to everything.
    #[tokio::test]
    async fn a_genuinely_dead_central_still_heals() {
        let c = BleCentral::ChannelClosed;
        let err = ble::scan(&c, Duration::from_secs(2))
            .await
            .expect_err("must fail");
        assert_eq!(
            err.fault(),
            BleFault::DeadCentral,
            "a dead CoreBluetooth session must still trigger reset_central + retry"
        );
        assert_eq!(err.text(), "Channel closed");
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
        assert!(is_dead_central(&res.err().unwrap()));
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
        assert!(is_dead_central(&res.err().unwrap()));
    }
}
