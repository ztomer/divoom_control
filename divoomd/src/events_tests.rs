//! Keying and resync order of the conflating event bus.

use super::*;
use serde_json::json;

#[test]
fn a_panel_event_is_keyed_by_panel_and_a_job_by_panel_and_kind() {
    let k = |v| Events::key(&v);
    assert_eq!(k(json!({"type": "status", "mac": "A"})), "status|A");
    assert_eq!(
        k(json!({"type": "status", "lan_ip": "1.2.3.4"})),
        "status|1.2.3.4"
    );
    assert_eq!(k(json!({"type": "status"})), "status|");
    assert_eq!(
        k(json!({"type": "activity", "mac": "A", "kind": "sysmon"})),
        k(json!({"type": "activity", "mac": "A", "kind": "music"})),
        "a panel shows one activity"
    );
    assert_ne!(
        k(json!({"type": "live_job_state", "mac": "A", "kind": "sysmon"})),
        k(json!({"type": "live_job_state", "mac": "A", "kind": "music"})),
        "each job has its own state"
    );
}

#[test]
fn resync_returns_each_keys_latest_value_in_publish_order() {
    let ev = Events::new(4);
    let mut rx = ev.subscribe();
    for i in 0..10 {
        let _ = ev.send(json!({"type": "status", "mac": "A", "n": i}));
    }
    let _ = ev.send(json!({"type": "selection", "mac": "B"}));
    let _ = ev.send(json!({"type": "status", "mac": "A", "n": 10}));
    let got = ev.resync(&mut rx);
    assert_eq!(
        got,
        vec![
            json!({"type": "selection", "mac": "B"}),
            json!({"type": "status", "mac": "A", "n": 10}),
        ]
    );
    // Re-attached at the tail: nothing stale is waiting behind the resync.
    assert!(rx.try_recv().is_err());
    let _ = ev.send(json!({"type": "status", "mac": "A", "n": 11}));
    assert_eq!(rx.try_recv().unwrap()["n"], 11);
}

#[test]
fn a_value_published_to_nobody_is_still_the_latest() {
    let ev = Events::new(4);
    assert!(ev.send(json!({"type": "status"})).is_err(), "no receivers");
    let mut rx = ev.subscribe();
    assert_eq!(ev.resync(&mut rx), vec![json!({"type": "status"})]);
}
