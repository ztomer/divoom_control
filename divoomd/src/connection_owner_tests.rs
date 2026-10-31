//! One owner holds a panel's link (D.DV2c), pinned without a radio.
//!
//! The owner's scheduled run of 2026-10-26 failed on all four panels with
//! "connect already in progress": it sent `connect` for panels the fleet was
//! linking at that moment (the daemon's startup restore held the one radio),
//! and the daemon refused each at once. Had it got further, its bare
//! `disconnect` would have dropped every panel and forgotten every saved link
//! -- the owner's `links.json` holds none today.

use crate::daemon::Daemon;
use crate::protocol::make_request;
use serde_json::json;

async fn link_mock(d: &Daemon, mac: &str, name: &str) {
    let r = crate::daemon_connect::cmd_connect(
        d,
        &make_request(
            "connect",
            Some(json!({"mock": true, "mac": mac, "name": name})),
            None,
        ),
    )
    .await;
    assert_eq!(r["success"], json!(true), "{r}");
}

/// A `connect` for a panel the fleet already holds is answered from the
/// fleet, the radio untouched: no second connection over the first.
#[tokio::test]
async fn a_connect_for_a_linked_panel_is_answered_from_the_fleet() {
    let d = Daemon::new();
    link_mock(&d, "PANEL-A", "Pixoo64-light").await;
    let r = crate::daemon_connect::cmd_connect(
        &d,
        &make_request("connect", Some(json!({"mac": "PANEL-A"})), None),
    )
    .await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert_eq!(r["already_linked"], json!(true), "{r}");
    assert_eq!(d.fleet.linked().await.len(), 1);
}

/// The scheduler borrows a panel the fleet holds and gives it back linked --
/// and nothing it does can drop the OTHER panels.
#[tokio::test]
async fn the_scheduler_borrows_a_held_panel_and_every_panel_stays_linked() {
    let d = Daemon::new();
    link_mock(&d, "PANEL-A", "Pixoo64-light").await;
    link_mock(&d, "PANEL-B", "Ditoo-light").await;

    let (lease, pixels) = crate::monthly_best_link::connect(&d, "PANEL-A")
        .await
        .expect("a held panel is borrowed");
    assert_eq!(pixels, 64);
    assert!(
        !lease.closes_on_release(),
        "the fleet's link is not the push's to close"
    );
    crate::monthly_best_link::release(&d, lease).await;

    for mac in ["PANEL-A", "PANEL-B"] {
        assert!(
            d.fleet.connected(mac).await.is_some(),
            "{mac} must still be linked after the scheduler's turn"
        );
    }
}

/// Structural: no daemon-internal code sends a `disconnect` request -- the
/// bare one drains the whole fleet and forgets every saved link. A panel is
/// let go of by `cmd_disconnect_one`, through a lease that opened it.
#[test]
fn no_internal_code_sends_a_disconnect_request() {
    let src = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut offenders = Vec::new();
    let mut stack = vec![src];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).unwrap().flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            let rust = path
                .extension()
                .is_some_and(|e| e.eq_ignore_ascii_case("rs"));
            if !rust
                || name.ends_with("_tests")
                || name.contains("_tests.")
                || name == "dispatch.rs"
            {
                continue;
            }
            let text = std::fs::read_to_string(&path).unwrap();
            let body = text.split("#[cfg(test)]").next().unwrap_or("");
            if body.contains(r#"command: "disconnect""#) {
                offenders.push(path.display().to_string());
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "a bare disconnect drops every panel: {offenders:?}"
    );
}

/// A connect that finds the radio busy WAITS, and is answered the moment the
/// holder links the very panel it asked for -- the restore-vs-scheduler race.
#[cfg(feature = "ble")]
#[tokio::test]
async fn a_connect_waiting_for_the_radio_is_answered_when_the_holder_links_its_panel() {
    use std::sync::atomic::Ordering;
    let d = std::sync::Arc::new(Daemon::new());
    d.connecting.store(true, Ordering::SeqCst); // the restore holds the radio
    let holder = d.clone();
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
        link_mock(&holder, "PANEL-A", "Pixoo64-light").await; // ...and links PANEL-A
    });
    let r = crate::daemon_connect::connect_waiting(
        &d,
        &make_request("connect", Some(json!({"mac": "PANEL-A"})), None),
        std::time::Duration::from_secs(5),
    )
    .await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert_eq!(r["already_linked"], json!(true), "{r}");
}

/// A wait has a bound: past it the answer is `busy`, and the holder keeps
/// the radio.
#[cfg(feature = "ble")]
#[tokio::test]
async fn a_connect_that_waits_past_its_bound_is_busy() {
    use std::sync::atomic::Ordering;
    let d = Daemon::new();
    d.connecting.store(true, Ordering::SeqCst);
    let r = crate::daemon_connect::connect_waiting(
        &d,
        &make_request("connect", Some(json!({"mac": "NEVER"})), None),
        std::time::Duration::from_millis(300),
    )
    .await;
    assert_eq!(r["success"], json!(false), "{r}");
    assert_eq!(r["error"], json!("connect already in progress"));
    assert!(d.connecting.load(Ordering::SeqCst));
}
