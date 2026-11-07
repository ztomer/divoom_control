//! A live widget is the most common writer to a panel, so it is usually how
//! a dropped link is noticed at all (P2.8).
//!
//! Before this, a live frame whose command could not be sent was a `false`
//! and nothing else: the panel kept reading as connected, no drop was
//! reported, and the job carried on saying "running" at a panel that was
//! gone. The `device_call` path learned the same thing and reported it; this
//! path now reports it too, through the same two broadcasts.

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use serde_json::json;

use super::frame::{push_live_frame, LiveFrame};
use crate::daemon::Daemon;
use crate::daemon_connect::status_payload;
use crate::mock_transport::MockTransport;
use crate::protocol::make_request;
use crate::socket_server::Handler;

const PANEL: &str = "P28_LIVE";

async fn daemon_with_panel() -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    d
}

async fn mock_of(d: &Daemon) -> MockTransport {
    let dev = d.fleet.get(PANEL).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    match &*transport {
        crate::daemon::DeviceTransport::Mock(m) => m.clone(),
        _ => panic!("expected the mock transport"),
    }
}

/// A frame that cannot be sent retires the link: the panel stops reading as
/// connected, and the drop is on the bus.
#[tokio::test]
async fn a_live_frame_that_cannot_be_sent_retires_the_link() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    let mut rx = d.tx.subscribe();
    // The panel's link goes away between the connect and the frame.
    mock.set_failing(true);

    let alive = Arc::new(AtomicBool::new(true));
    let landed = push_live_frame(
        &d,
        PANEL,
        "sysmon",
        &alive,
        LiveFrame {
            rgb: vec![0u8; 2 * 2 * 3],
            w: 2,
            h: 2,
            time_ms: 100,
        },
    )
    .await;
    assert!(!landed, "the frame could not be sent");

    let named = d
        .handle(make_request(
            "device_status",
            Some(json!({ "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(
        named["connected"],
        json!(false),
        "the dropped panel still reads as connected: {named}"
    );

    let mut disconnected = false;
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("status") && ev["connected"] == json!(false) {
            assert_eq!(ev["state"], json!("disconnected"), "{ev}");
            disconnected = true;
        }
    }
    assert!(disconnected, "the drop was not reported on the bus");
}

/// The drop is reported the way the daemon reports every other one: the same
/// status shape a user-initiated disconnect sends.
#[tokio::test]
async fn the_reported_drop_is_the_shape_the_daemon_uses() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    mock.set_failing(true);
    let alive = Arc::new(AtomicBool::new(true));
    let _ = push_live_frame(
        &d,
        PANEL,
        "sysmon",
        &alive,
        LiveFrame {
            rgb: vec![0u8; 2 * 2 * 3],
            w: 2,
            h: 2,
            time_ms: 100,
        },
    )
    .await;

    let expected = status_payload(false, Some(PANEL), Some("disconnected"));
    assert_eq!(expected["type"], json!("status"));
    assert_eq!(expected["connected"], json!(false));
    assert_eq!(expected["mac"], json!(PANEL));
}

fn tiny_frame() -> LiveFrame {
    LiveFrame {
        rgb: vec![0u8; 2 * 2 * 3],
        w: 2,
        h: 2,
        time_ms: 100,
    }
}

/// Yield until `cond` holds; false if it never did.
async fn settle(cond: impl Fn() -> bool) -> bool {
    for _ in 0..10_000 {
        if cond() {
            return true;
        }
        tokio::task::yield_now().await;
    }
    cond()
}

/// D.LINKDROP: a write already IN FLIGHT on a link fails after a reconnect
/// replaced that link. The failure belongs to the OLD link. It used to be
/// handed to `link_failed(mac)`, which retired whatever link the mac named
/// NOW -- the healthy new one -- and told every client the panel had
/// dropped, seconds after it came back.
#[tokio::test]
async fn a_late_failure_on_a_replaced_link_leaves_the_new_link_alone() {
    let d = daemon_with_panel().await;
    let old = mock_of(&d).await;
    old.set_failing(true);
    let gate = old.hold_writes().await;

    let alive = Arc::new(AtomicBool::new(true));
    let (d2, a2) = (d.clone(), alive.clone());
    let push =
        tokio::spawn(async move { push_live_frame(&d2, PANEL, "sysmon", &a2, tiny_frame()).await });
    assert!(
        settle(|| old.writes_waiting() >= 1).await,
        "the frame never reached the wire"
    );

    // The panel comes back on a new link while the old write is in flight.
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let dev = d.fleet.get(PANEL).await.expect("the panel is in the fleet");
    let new_link = dev.link().await.expect("the panel is linked again");
    let mut rx = d.tx.subscribe();

    drop(gate); // the old write now fails
    assert!(!push.await.expect("push task"), "the old write failed");

    let now = dev
        .link()
        .await
        .expect("the old link's failure unlinked the panel's NEW link");
    assert!(Arc::ptr_eq(&now, &new_link), "the panel's link changed");
    assert!(!new_link.is_retired(), "the new link was retired");
    while let Ok(ev) = rx.try_recv() {
        assert!(
            !(ev["type"] == json!("status") && ev["connected"] == json!(false)),
            "a drop was reported for a panel whose new link is fine: {ev}"
        );
    }
}

/// D.LINKDROP sibling: a frame the stop fence drops (its job was stopped
/// while the frame waited in the queue) did not land. It used to come back
/// `Ok(())` from the fence and be reported as landed -- the screen record
/// and an `activity` event naming a widget the user had just stopped.
#[tokio::test]
async fn a_frame_dropped_by_the_stop_fence_is_not_reported_as_landed() {
    let d = daemon_with_panel().await;
    let dev = d.fleet.get(PANEL).await.expect("the panel is in the fleet");
    let link = dev.link().await.expect("the panel is linked");
    let permit = link.queue.acquire(None).await.expect("hold the panel");

    let alive = Arc::new(AtomicBool::new(true));
    let (d2, a2) = (d.clone(), alive.clone());
    let push =
        tokio::spawn(async move { push_live_frame(&d2, PANEL, "sysmon", &a2, tiny_frame()).await });
    assert!(
        settle(|| link.queue.pending() >= 1).await,
        "the frame never queued behind the hold"
    );
    alive.store(false, std::sync::atomic::Ordering::SeqCst); // the job is stopped
    let mut rx = d.tx.subscribe();
    drop(permit);

    assert!(
        !push.await.expect("push task"),
        "a frame the stop fence dropped was reported as landed"
    );
    assert!(
        dev.screen().is_none(),
        "the screen records a frame that never landed"
    );
    while let Ok(ev) = rx.try_recv() {
        assert_ne!(
            ev["type"],
            json!("activity"),
            "activity for a dropped frame: {ev}"
        );
    }
    let sent = mock_of(&d).await.sent_commands.lock().unwrap().len();
    assert_eq!(sent, 0, "a fenced frame reached the panel");
}

/// D.LINKDROP sibling: a frame that lands on a link a reconnect has since
/// replaced landed on a connection that is gone. The new link starts with
/// no screen record (a reconnected panel may have been power-cycled), and a
/// late landing on the OLD link must not write one back.
#[tokio::test]
async fn a_landing_on_a_replaced_link_is_not_recorded_on_the_new_one() {
    let d = daemon_with_panel().await;
    let old = mock_of(&d).await;
    let gate = old.hold_writes().await;
    let alive = Arc::new(AtomicBool::new(true));
    let (d2, a2) = (d.clone(), alive.clone());
    let push =
        tokio::spawn(async move { push_live_frame(&d2, PANEL, "sysmon", &a2, tiny_frame()).await });
    assert!(
        settle(|| old.writes_waiting() >= 1).await,
        "the frame never reached the wire"
    );
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let mut rx = d.tx.subscribe();
    drop(gate);
    let _ = push.await.expect("push task");

    let dev = d.fleet.get(PANEL).await.expect("the panel is in the fleet");
    assert!(
        dev.screen().is_none(),
        "the new link's screen records a frame the old link carried"
    );
    while let Ok(ev) = rx.try_recv() {
        assert_ne!(
            ev["type"],
            json!("activity"),
            "activity from the old link: {ev}"
        );
    }
}
