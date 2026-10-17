//! The table's own invariants; `tests/connection_census.rs` drives it through
//! the real accept loop.

use super::*;

#[test]
fn an_entry_lives_exactly_as_long_as_its_guard() {
    let t = Connections::new();
    let a = t.open("unix", Some(7));
    let b = t.open("tcp", None);
    b.mark_subscription();
    assert_eq!(t.count(Kind::Request), 1);
    assert_eq!(t.count(Kind::Subscription), 1);
    drop(a);
    assert_eq!(t.count(Kind::Request), 0);
    drop(b);
    assert_eq!(t.snapshot()["open"], json!([]));
}

#[test]
fn the_snapshot_names_the_command_in_flight_and_forgets_it_after() {
    let t = Connections::new();
    let c = t.open("unix", None);
    c.running(Some("sync_artwork"));
    assert_eq!(t.snapshot()["open"][0]["command"], "sync_artwork");
    assert!(t.snapshot()["open"][0]["command_ms"].is_u64());
    c.running(None);
    assert!(t.snapshot()["open"][0]["command"].is_null());
}

#[test]
fn limits_are_reported_per_transport() {
    let t = Connections::new();
    t.set_limits("unix", 64, 8);
    assert_eq!(
        t.snapshot()["limits"],
        json!({ "unix": { "connections": 64, "subscriptions": 8 } })
    );
}
