//! Protocol autoprobe decision flow, ported from `divoom_lib/ble_probe.py`.
//!
//! On first connect the transport doesn't know whether the device speaks iOS-LE or
//! Basic framing. It sends a 0x46 query in each framing and picks the one that
//! answers: iOS-LE first, then Basic, defaulting to Basic if neither replies. The
//! actual "send a probe + wait for the reply" is the transport's job (hardware);
//! here it's abstracted behind [`Prober`] so the DECISION (order + default) is
//! pinned by tests without a device.

use std::future::Future;
use std::pin::Pin;

/// The two BLE wire framings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Protocol {
    Basic,
    IosLe,
}

/// Sends a 0x46 probe in the given framing and reports whether the device answered
/// (with the matching response, within the probe timeout). The real transport
/// implements this; tests use a mock.
pub trait Prober {
    fn probe<'a>(&'a self, framing: Protocol) -> Pin<Box<dyn Future<Output = bool> + Send + 'a>>;
}

/// Detect the device's framing: try iOS-LE, then Basic, default Basic. Mirrors
/// `autoprobe_protocol` (iOS-LE is attempted first; Basic is the fallback and the
/// default when neither answers).
pub async fn autoprobe<P: Prober>(prober: &P) -> Protocol {
    if prober.probe(Protocol::IosLe).await {
        return Protocol::IosLe;
    }
    if prober.probe(Protocol::Basic).await {
        return Protocol::Basic;
    }
    Protocol::Basic
}
