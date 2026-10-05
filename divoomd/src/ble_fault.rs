//! Deciding, from a still-typed `btleplug::Error`, whether the daemon's
//! `CoreBluetooth` central is the thing that died.
//!
//! The daemon rebuilds the central and retries once when — and only when — the
//! central is gone. That needs exactly one bit, and the bit used to be read out
//! of btleplug's `Display` output with four substring probes. That made a
//! dependency's prose load-bearing: a reword upstream silently stopped the
//! self-heal and nothing in this repo would have said so.
//!
//! So the bit is decided ONCE, here, while `btleplug::Error` is still the typed
//! enum it is at the `?` sites, and it travels as [`BleFault`] — an enum THIS
//! crate owns. Every btleplug result is converted at the boundary that produces
//! it (`ble.rs`, `ble/connect.rs`, `central.rs`), the daemon's own timeout guards
//! state their answer directly instead of hiding it in a message, and
//! `daemon_connect` reads nothing but [`BleFault`]. A rename upstream can then
//! no longer change which errors retry: a new variant fails the build (the match
//! below has no wildcard arm), and the one place the type is already gone is
//! pinned by a test instead of by hope.
//!
//! Mirrors `antiknob`'s `host::grants`: ask the authority, keep the answer in a
//! type you own, and unit-test every arm of the match that turns it into a
//! decision. Not copied for its domain — a TCC grant is two booleans macOS hands
//! over exactly; a dead central is a judgement call, so the judgement lives here
//! and only here.

use std::fmt;

/// What the daemon should do about a BLE failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BleFault {
    /// The `CoreBluetooth` session itself is gone — the central ended after a
    /// device disconnect or a Bluetooth toggle, or an operation on it never came
    /// back at all. The cached `Adapter` cannot recover, so dropping it and
    /// building a fresh one is the only thing that can help.
    DeadCentral,
    /// Everything else. Retrying through a fresh central cannot fix an absent
    /// device, a missing characteristic, a revoked permission or a vanished
    /// peripheral, so the daemon must NOT spend a rebuild on it.
    Other,
}

/// A BLE failure, carrying the decision with it.
///
/// The message is kept byte-for-byte as the stack rendered it, so every reply the
/// user sees (`"scan failed: …"`) is unchanged by the classification landing
/// here instead of in a caller.
#[derive(Debug)]
pub struct BleError {
    text: String,
    fault: BleFault,
}

impl BleError {
    /// Classify a `btleplug` error while it is still the typed enum, and keep
    /// its message for the user-facing reply.
    ///
    /// Takes a reference, not the error: `Display` is the only way to keep the
    /// message whole, and `Display` borrows. Nothing is lost — the dependency's
    /// error is owned by the `?` that produced it, which is exactly where this
    /// is called from.
    ///
    /// There is deliberately no `_ =>` arm. `btleplug` adding, removing or
    /// renaming a variant must be a COMPILE error here: that is the whole
    /// guarantee. A wildcard would let a new variant fall through to whichever
    /// arm happened to be written last, which is exactly the silent-narrowing
    /// failure this module exists to end.
    #[must_use]
    pub fn from_btle(err: &btleplug::Error) -> Self {
        let fault = match err {
            // The one variant that can mean "the central is gone", and the one
            // place a dependency's wording is still read — because by then there
            // is no type left to read. See `DEAD_SESSION_MARKERS`.
            btleplug::Error::Other(inner) if is_dead_session(inner.as_ref()) => BleFault::DeadCentral,

            // Every other variant is `BleFault::Other`, and NOT ONE of them is
            // asked anything about its wording. Three reasons, by group:
            //
            //   `RuntimeError` — 0.13's prompt answer for a peripheral that has
            //   vanished, or a reply that matched no branch. 0.12 HUNG on those,
            //   our 20s guard turned the hang into "...timed out: central may be
            //   stale", and the daemon rebuilt the central and retried —
            //   pointlessly, since rebuilding cannot conjure a vanished device
            //   back. 0.13 makes that retry stop, deliberately, and the decision
            //   is pinned from the real seam by `central.rs`'s
            //   `prompt_runtime_errors_are_not_central_faults`.
            //
            //   `TimedOut` — btleplug renders it "Timed out after 10s", a CAPITAL
            //   T, so the lowercase `contains("timed out")` probe this replaces
            //   did NOT match it and it never triggered a rebuild. Preserved:
            //   a peripheral that will not connect in time is not a dead central,
            //   and nothing in this crate asks btleplug for a timeout — every
            //   bounded operation uses our own guards — so the variant is not a
            //   shape this daemon currently produces at all.
            //
            //   the rest — absent device, missing characteristic, revoked
            //   permission, bad address: none of them is fixed by a new central.
            //
            // The one consequence of "never asked", stated plainly: a
            // `RuntimeError`/`NotSupported` payload that happened to contain one
            // of the four old marker words used to read as a dead central and now
            // does not. No payload in btleplug 0.13.4 does — grep-verified across
            // every `RuntimeError(` and `NotSupported(` in the crate — so no real
            // error changes bucket, but the wording independence is the point of
            // the change rather than an accident of it.
            btleplug::Error::PermissionDenied
            | btleplug::Error::DeviceNotFound
            | btleplug::Error::NotConnected
            | btleplug::Error::UnexpectedCallback
            | btleplug::Error::UnexpectedCharacteristic
            | btleplug::Error::NoSuchCharacteristic
            | btleplug::Error::NoAdapterAvailable
            | btleplug::Error::NotSupported(_)
            | btleplug::Error::TimedOut(_)
            | btleplug::Error::Uuid(_)
            | btleplug::Error::InvalidBDAddr(_)
            | btleplug::Error::RuntimeError(_)
            // An `Other` that is not a dead session: `corebluetooth` produces one
            // of these when the adapter never reached the powered-on state, and
            // rebuilding the central cannot fix that.
            | btleplug::Error::Other(_) => BleFault::Other,
        };
        Self {
            text: err.to_string(),
            fault,
        }
    }

    /// A failure this crate produced, known to mean the central is gone.
    ///
    /// Only for OUR OWN timeout guards. Each of them exists because an operation
    /// on a wedged `CoreBluetooth` session never returns — with no error at all —
    /// so the hang has to be turned into a failure somehow, and "the central did
    /// not answer" is what that failure means. Saying so in the type is why the
    /// self-heal can no longer be disabled by rewording a sentence here.
    pub fn dead_central(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            fault: BleFault::DeadCentral,
        }
    }

    /// A failure this crate produced, known NOT to be worth a central rebuild.
    #[must_use]
    pub fn other(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            fault: BleFault::Other,
        }
    }

    /// The one bit `daemon_connect` acts on.
    #[must_use]
    pub const fn fault(&self) -> BleFault {
        self.fault
    }

    /// The message, exactly as the stack rendered it.
    #[must_use]
    pub fn text(&self) -> &str {
        &self.text
    }
}

impl fmt::Display for BleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.text)
    }
}

impl std::error::Error for BleError {}

/// Markers of a dead `CoreBluetooth` session, consulted ONLY from inside
/// `btleplug::Error::Other`.
///
/// This is the last place in the daemon that reads a dependency's prose, and it
/// has to: btleplug's macOS backend converts its internal channel-closed signal
/// with `impl From<SendError> for Error { Error::Other("Channel closed".to_string().into()) }`
/// (`src/corebluetooth/peripheral.rs`) — a boxed bare `String`, whose `source()`
/// is `None` and whose concrete type is unnamed. By the time it reaches us there
/// is genuinely nothing else to read. What changed is that it can no longer fail
/// SILENTLY: `the_shape_btleplug_actually_produces_is_still_recognised` builds
/// the error through btleplug's own conversion and fails if the wording moves.
///
/// `"Channel closed"` is the only marker any real btleplug 0.13.4 backend emits.
/// The other three are the wording of this crate's own timeout guards, which no
/// longer travel as prose at all — they are kept because this arm has always
/// accepted them, and a backend that reports a dead session in its own words
/// must still heal.
const DEAD_SESSION_MARKERS: &[&str] = &["Channel closed", "timed out", "stale", "central"];

fn is_dead_session(inner: &(dyn std::error::Error + 'static)) -> bool {
    let text = inner.to_string();
    DEAD_SESSION_MARKERS
        .iter()
        .any(|marker| text.contains(marker))
}

#[cfg(test)]
mod tests;
