//! Tests for the BLE fault classifier. Split out of `ble_fault.rs` to keep
//! that file under the 500-LOC ground rule; `is_dead_central_by_prose` in
//! here is the old implementation, kept verbatim as the behaviour oracle.

use super::*;
use std::str::FromStr as _;
use std::time::Duration;

/// The classifier this module replaced, verbatim.
///
/// It is the ORACLE for `old_and_new_agree_on_every_error_the_daemon_can_see`,
/// which is the only available proof that a dependency-free classification
/// kept the same behaviour — the alternative is a daemon and a device.
///
/// It may be deleted the moment the daemon can be compared against its own
/// history on real hardware: run both against the same dead-central session
/// and show one verdict each. Until then it is the specification, not
/// dead code, and `check_no_allow` has no bearing on it.
fn is_dead_central_by_prose(err: &str) -> bool {
    err.contains("Channel closed")
        || err.contains("timed out")
        || err.contains("stale")
        || err.contains("central")
}

/// Every arm of the classifier, with the reason each one is what it is.
#[test]
fn each_arm_is_pinned() {
    let other = [
        ("permission", btleplug::Error::PermissionDenied),
        ("device not found", btleplug::Error::DeviceNotFound),
        ("not connected", btleplug::Error::NotConnected),
        ("unexpected callback", btleplug::Error::UnexpectedCallback),
        (
            "unexpected characteristic",
            btleplug::Error::UnexpectedCharacteristic,
        ),
        (
            "no such characteristic",
            btleplug::Error::NoSuchCharacteristic,
        ),
        ("no adapter", btleplug::Error::NoAdapterAvailable),
        (
            "not supported",
            btleplug::Error::NotSupported("read the CCCD".into()),
        ),
        (
            "btleplug's own timeout",
            btleplug::Error::TimedOut(Duration::from_secs(10)),
        ),
        (
            "bad uuid",
            btleplug::Error::from("not-a-uuid".parse::<uuid::Uuid>().unwrap_err()),
        ),
        (
            "bad address",
            btleplug::Error::from(btleplug::api::BDAddr::from_str("nope").unwrap_err()),
        ),
        (
            "0.13's prompt error",
            btleplug::Error::RuntimeError("Peripheral no longer available".into()),
        ),
    ];
    for (why, err) in other {
        assert_eq!(
            BleError::from_btle(&err).fault(),
            BleFault::Other,
            "{why} must not spend a central rebuild"
        );
    }

    // The other arm: the dead session btleplug can no longer type for us.
    let closed = btleplug::Error::Other("Channel closed".into());
    assert_eq!(
        BleError::from_btle(&closed).fault(),
        BleFault::DeadCentral,
        "a dead CoreBluetooth session must still trigger reset_central + retry"
    );
}

/// This crate's own timeout guards are `DeadCentral` because of WHAT they
/// are — a bound on an operation that never came back — not because of how
/// they are worded. Rewriting the message must not disarm the self-heal.
#[test]
fn our_own_timeout_guards_are_dead_centrals_by_construction() {
    let guards = [
        "scan timed out: central may be stale (Channel closed)",
        "BLE scan start timed out: central may be stale (Channel closed)",
        "BLE discovery timed out: central may be stale (Channel closed)",
        "BLE connect timed out",
        "BLE discover_services timed out",
        "BLE subscribe timed out",
        "BLE write timed out (device unreachable)",
        // Same fault, words chosen to share nothing with the old probes.
        "the radio never answered",
    ];
    for msg in guards {
        assert_eq!(
            BleError::dead_central(msg).fault(),
            BleFault::DeadCentral,
            "{msg}"
        );
    }
}

/// The faults this crate raises that are NOT central faults, each stated by
/// what it means rather than by the words that carry it.
#[test]
fn our_own_other_failures_are_not_central_faults() {
    let others = [
        "no BLE adapter",
        "device not found in scan",
        "no write characteristic",
        "no notify characteristic",
        "payload must contain at least the command id",
        "the device is simply switched off",
    ];
    for msg in others {
        assert_eq!(BleError::other(msg).fault(), BleFault::Other, "{msg}");
    }
}

/// A backend that reports a dead session in its OWN words still heals: the
/// `Other` arm accepts every marker the old prose probe accepted, not just
/// the one btleplug happens to use today.
#[test]
fn a_dead_session_named_in_the_backends_own_words_still_heals() {
    for msg in [
        "Channel closed",
        "d-Bus call timed out",
        "the adapter looks stale",
        "no reply from the central",
    ] {
        let raw = btleplug::Error::Other(msg.into());
        assert_eq!(
            BleError::from_btle(&raw).fault(),
            BleFault::DeadCentral,
            "{msg}"
        );
    }
}

/// An `Other` that is not a dead session must not spend a rebuild —
/// `corebluetooth/adapter.rs` produces one of these when the adapter never
/// reached the powered-on state, and rebuilding cannot fix that.
#[test]
fn an_other_that_is_not_a_dead_session_does_not_heal() {
    let raw = btleplug::Error::Other("Adapter failed to connect.".into());
    assert_eq!(BleError::from_btle(&raw).fault(), BleFault::Other);
}

/// The decision no longer depends on a message's wording, for the variant
/// where that was the riskiest: 0.13's prompt-error family. A marker word
/// inside its payload used to force a pointless central rebuild; it must not
/// now, and it must not later.
#[test]
fn a_prompt_error_is_judged_by_its_variant_not_its_wording() {
    let runtime = btleplug::Error::RuntimeError("central may be stale".into());
    assert_eq!(BleError::from_btle(&runtime).fault(), BleFault::Other);
    let unsupported = btleplug::Error::NotSupported("a stale central".into());
    assert_eq!(BleError::from_btle(&unsupported).fault(), BleFault::Other);
}

/// The behaviour-preservation proof: the old prose probe and the new typed
/// classifier must return the same verdict for every error the BLE layer can
/// hand `daemon_connect` — every `btleplug` variant, plus every message this
/// crate raises.
///
/// This is the strongest evidence available without hardware, and it is only
/// evidence because both sides run: the left column is the function that was
/// in production, the right is what shipped instead.
#[test]
fn old_and_new_agree_on_every_error_the_daemon_can_see() {
    let raw = [
        btleplug::Error::PermissionDenied,
        btleplug::Error::DeviceNotFound,
        btleplug::Error::NotConnected,
        btleplug::Error::UnexpectedCallback,
        btleplug::Error::UnexpectedCharacteristic,
        btleplug::Error::NoSuchCharacteristic,
        btleplug::Error::NoAdapterAvailable,
        btleplug::Error::NotSupported("read the CCCD".into()),
        btleplug::Error::TimedOut(Duration::from_secs(10)),
        btleplug::Error::TimedOut(Duration::from_millis(1200)),
        btleplug::Error::from("not-a-uuid".parse::<uuid::Uuid>().unwrap_err()),
        btleplug::Error::from(btleplug::api::BDAddr::from_str("nope").unwrap_err()),
        btleplug::Error::RuntimeError("Peripheral no longer available".into()),
        btleplug::Error::RuntimeError("Unexpected CoreBluetooth clear reply".into()),
        btleplug::Error::Other("Channel closed".into()),
        btleplug::Error::Other("Adapter failed to connect.".into()),
        btleplug::Error::Other("Service with UUID x not found.".into()),
    ]
    .into_iter();

    let from_this_crate = [
        BleError::dead_central("scan timed out: central may be stale (Channel closed)"),
        BleError::dead_central("BLE scan start timed out: central may be stale (Channel closed)"),
        BleError::dead_central("BLE discovery timed out: central may be stale (Channel closed)"),
        BleError::dead_central("BLE connect timed out"),
        BleError::dead_central("BLE discover_services timed out"),
        BleError::dead_central("BLE subscribe timed out"),
        BleError::dead_central("BLE write timed out (device unreachable)"),
        BleError::other("no BLE adapter"),
        BleError::other("device not found in scan"),
        BleError::other("no write characteristic"),
        BleError::other("no notify characteristic"),
        BleError::other("payload must contain at least the command id"),
        BleError::other("scan send_command not supported on LAN"),
    ];

    for err in raw.map(|e| BleError::from_btle(&e)).chain(from_this_crate) {
        let old = is_dead_central_by_prose(err.text());
        let new = matches!(err.fault(), BleFault::DeadCentral);
        assert_eq!(
            new,
            old,
            "classification changed for {:?}: old said {old}, new says {new}",
            err.text()
        );
    }
}

/// The message IS the user-facing reply, so classifying it must not have
/// altered one — a fault that quietly rewrites what the user reads would be
/// a behaviour change nobody asked for.
#[test]
fn the_message_is_preserved_byte_for_byte() {
    let cases = [
        (
            btleplug::Error::RuntimeError("Peripheral no longer available".into()),
            "Runtime Error: Peripheral no longer available",
        ),
        (btleplug::Error::PermissionDenied, "Permission denied"),
        (
            btleplug::Error::Other("Channel closed".into()),
            "Channel closed",
        ),
    ];
    for (raw, expected) in cases {
        let err = BleError::from_btle(&raw);
        assert_eq!(err.text(), expected);
        assert_eq!(err.to_string(), expected, "Display must be the message");
    }
}

/// The one thing a reword upstream can still break, and it now breaks
/// LOUDLY: btleplug's macOS backend reports a dead session as
/// `Error::Other(<a bare String rendering as "Channel closed">)`, so this is
/// the shape the daemon must recognise.
///
/// The error is built the way btleplug builds it — through its own
/// `From<SendError>` — so neither the variant nor the wording is assumed here;
/// both are read off the value. If upstream renames the variant the build
/// stops, and if it rewords the message THIS fails, which is the point.
#[cfg(target_vendor = "apple")]
#[test]
fn the_shape_btleplug_actually_produces_is_still_recognised() {
    use futures::channel::mpsc::Sender;
    use futures::SinkExt as _;

    // A `SendError` is "the receiver is gone", i.e. the CoreBluetooth event
    // loop dropped its channel: exactly a dead session.
    let (mut tx, rx) = futures::channel::mpsc::channel::<()>(1);
    drop(rx);
    let send_error: futures::channel::mpsc::SendError =
        futures::executor::block_on(Sender::send(&mut tx, ())).unwrap_err();

    let err = btleplug::Error::from(send_error);
    assert_eq!(
        err.to_string(),
        "Channel closed",
        "btleplug reworded its dead-session error; update DEAD_SESSION_MARKERS \
         and this module's WHY comments to match what it says now"
    );
    assert_eq!(
        BleError::from_btle(&err).fault(),
        BleFault::DeadCentral,
        "the dead session must still trigger reset_central + retry"
    );
}

/// btleplug renders the SAME dead session two different ways, and only one of
/// them used to heal.
///
/// Its `From<SendError> for Error` throws the send error away and substitutes a
/// bare `"Channel closed"`, so `start_scan`/`stop_scan`/`peripherals`/`connect`/
/// `write` all produce text this crate recognises. `corebluetooth/adapter.rs:236`
/// bypasses that conversion with `.map_err(|e| Error::Other(Box::new(e)))` and
/// keeps the real `futures::channel::mpsc::SendError`, whose `Display` is
/// "send failed because receiver is gone".
///
/// The error is BUILT here rather than written as a string, so this test fails
/// if `SendError`'s wording ever changes — which is the point: the alternative
/// would be a test asserting our own constant matches itself.
#[tokio::test]
async fn a_dead_session_surfaced_the_other_way_still_heals() {
    // Exactly what adapter.rs:236 builds: a send into a channel whose receiver
    // has been dropped, boxed as the error.
    let err = dropped_receiver_send_error().await;

    // Sanity: this really is the rendering that used to be missed.
    let text = err.to_string();
    assert_eq!(text, "send failed because receiver is gone", "{text}");
    for stale in crate::ble_fault::DEAD_SESSION_MARKERS {
        assert!(
            !text.contains(stale),
            "this case is only interesting while NONE of the primary markers \
             match it -- {stale:?} started matching, so the alternative \
             rendering may no longer exist"
        );
    }

    assert_eq!(
        crate::ble_fault::BleError::from_btle(&err).fault(),
        crate::ble_fault::BleFault::DeadCentral,
        "a dropped event-channel receiver IS a dead CoreBluetooth session; it \
         must rebuild the central and retry, exactly as the 'Channel closed' \
         rendering of the same condition does"
    );
}

/// The two renderings must agree, which is the actual invariant.
///
/// One of them reaching `DeadCentral` is not enough: if only the alternative
/// matched, the primary arm could have rotted and every existing test would
/// still pass.
#[tokio::test]
async fn both_renderings_of_one_dead_session_classify_the_same() {
    let primary = btleplug::Error::Other("Channel closed".to_string().into());
    assert_eq!(
        crate::ble_fault::BleError::from_btle(&primary).fault(),
        crate::ble_fault::BleFault::DeadCentral,
        "btleplug's own From<SendError> rendering"
    );

    let alt = dropped_receiver_send_error().await;
    assert_eq!(
        crate::ble_fault::BleError::from_btle(&alt).fault(),
        crate::ble_fault::BleError::from_btle(&primary).fault(),
        "the same dead session, rendered two ways by upstream, must not \
         classify two ways here"
    );
}

/// Build the error `corebluetooth/adapter.rs:236` produces.
///
/// A send into a channel whose receiver has been dropped, boxed as the error
/// without passing through btleplug's own `From<SendError>` conversion. Going
/// through the real type rather than writing the string by hand is what makes
/// these tests able to notice if `SendError`'s wording changes.
async fn dropped_receiver_send_error() -> btleplug::Error {
    use futures::SinkExt;
    let (tx, rx) = futures::channel::mpsc::channel::<u8>(1);
    drop(rx);
    let mut tx = tx;
    let raw = tx
        .send(1)
        .await
        .expect_err("receiver is dropped, so this fails");
    btleplug::Error::Other(Box::new(raw))
}
