//! Screen leases: an agent borrows a panel and gives it back (P4.6).
//!
//! Before leases, an agent drawing on a panel ran into its live widget two
//! ways: the agent's `show_image` STOPPED the widget for good
//! (`preempt_conflicting_live_jobs`), and a widget that was not stopped
//! painted over the agent on its next tick. A crashed agent left its frame
//! up forever. Every case drives the real dispatcher against the mock
//! transport, which records each command the daemon sends.

use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::{json, Value};

const MAC: &str = "LEASE_A";

async fn daemon() -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let r = ask(&d, "connect", json!({ "mock": true, "mac": MAC })).await;
    assert_eq!(r["success"], json!(true), "{r}");
    d
}

async fn ask(d: &Daemon, command: &str, args: Value) -> Value {
    d.handle(make_request(command, Some(args), None)).await
}

async fn call(d: &Daemon, method: &str, token: Option<&str>, kwargs: Value) -> Value {
    let mut args = json!({ "mac": MAC, "method": method, "kwargs": kwargs });
    if let Some(t) = token {
        args["token"] = json!(t);
    }
    ask(d, "device_call", args).await
}

fn frame(edge: usize) -> Value {
    let rgb = base64::engine::general_purpose::STANDARD.encode(vec![200u8; edge * edge * 3]);
    json!({ "w": edge, "h": edge, "frames": [{ "rgb_b64": rgb, "time_ms": 100 }] })
}

async fn sent(d: &Daemon) -> usize {
    let t = d
        .fleet
        .get(MAC)
        .await
        .expect("known")
        .transport()
        .await
        .expect("linked");
    match &*t {
        DeviceTransport::Mock(m) => m.sent_commands.lock().unwrap().len(),
        _ => panic!("expected the mock"),
    }
}

async fn wait_for_sent(d: &Daemon, n: usize, budget: Duration) -> usize {
    let deadline = tokio::time::Instant::now() + budget;
    loop {
        let c = sent(d).await;
        if c >= n || tokio::time::Instant::now() >= deadline {
            return c;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

async fn acquire(d: &Daemon, ttl_ms: u64) -> String {
    let r = ask(
        d,
        "lease_acquire",
        json!({ "mac": MAC, "ttl_ms": ttl_ms, "holder": "agent-1" }),
    )
    .await;
    assert_eq!(r["success"], json!(true), "{r}");
    r["token"].as_str().expect("a token").to_string()
}

async fn job_kind(d: &Daemon) -> Option<String> {
    d.fleet.get(MAC).await.expect("known").live_kind().await
}

#[tokio::test]
async fn a_lease_needs_a_bounded_ttl() {
    let d = daemon().await;
    for args in [
        json!({ "mac": MAC }),
        json!({ "mac": MAC, "ttl_ms": 10 }),
        json!({ "mac": MAC, "ttl_ms": 3_600_000 }),
    ] {
        let r = ask(&d, "lease_acquire", args.clone()).await;
        assert_eq!(r["code"], json!("bad_request"), "{args}: {r}");
        assert!(
            r["error"].as_str().is_some_and(|e| e.contains("ttl_ms")),
            "{r}"
        );
    }
    let r = ask(
        &d,
        "lease_renew",
        json!({ "token": "nope", "ttl_ms": 5000 }),
    )
    .await;
    assert_eq!(r["code"], json!("lease_expired"), "{r}");
    let r = ask(&d, "lease_release", json!({ "token": "nope" })).await;
    assert_eq!(r["code"], json!("lease_expired"), "{r}");
}

#[tokio::test]
async fn while_leased_only_the_holder_draws_and_others_hear_who() {
    let d = daemon().await;
    let token = acquire(&d, 30_000).await;

    let theirs = call(&d, "show_image", None, frame(16)).await;
    assert_eq!(theirs["success"], json!(false), "{theirs}");
    assert_eq!(theirs["code"], json!("screen_leased"), "{theirs}");
    assert_eq!(theirs["holder"], json!("agent-1"), "{theirs}");
    assert!(
        theirs["remaining_ms"].as_u64().is_some_and(|m| m > 25_000),
        "{theirs}"
    );

    let again = ask(&d, "lease_acquire", json!({ "mac": MAC, "ttl_ms": 5000 })).await;
    assert_eq!(
        again["code"],
        json!("screen_leased"),
        "a second holder: {again}"
    );
    let excl = ask(&d, "exclusive_start", json!({ "token": "someone" })).await;
    assert_eq!(
        excl["success"],
        json!(false),
        "exclusive mode cannot steal it: {excl}"
    );

    let before = sent(&d).await;
    let mine = call(&d, "show_image", Some(&token), frame(16)).await;
    assert_eq!(mine["success"], json!(true), "{mine}");
    assert!(
        sent(&d).await > before,
        "the holder's frame reached the panel"
    );

    let r = ask(&d, "lease_release", json!({ "token": token })).await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert_eq!(
        r["restored"],
        json!("none"),
        "no widget to go back to, said plainly: {r}"
    );
    let after = call(&d, "show_image", None, frame(16)).await;
    assert_eq!(
        after["success"],
        json!(true),
        "released, anyone draws: {after}"
    );
}

#[tokio::test]
async fn the_widget_pauses_under_a_lease_and_comes_back_when_it_ends() {
    let d = daemon().await;
    let idle = sent(&d).await;
    let r = ask(
        &d,
        "live_job_start",
        json!({ "mac": MAC, "kind": "sysmon", "params": { "size": 16 } }),
    )
    .await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert!(
        wait_for_sent(&d, idle + 1, Duration::from_secs(3)).await > idle,
        "the widget drew"
    );
    tokio::time::sleep(Duration::from_millis(300)).await;
    let one_frame = sent(&d).await - idle;

    let token = acquire(&d, 30_000).await;
    let mine = call(&d, "show_image", Some(&token), frame(16)).await;
    assert_eq!(mine["success"], json!(true), "{mine}");
    assert_eq!(
        job_kind(&d).await.as_deref(),
        Some("sysmon"),
        "the holder's frame PAUSES the widget, never stops it"
    );

    // Across a whole widget tick (sysmon: 5 s), nothing but the holder's
    // frame reaches the panel.
    let held = sent(&d).await;
    tokio::time::sleep(Duration::from_millis(5_600)).await;
    assert_eq!(
        sent(&d).await,
        held,
        "a widget frame painted over the lease"
    );

    // Released, the widget's newest frame is painted AT ONCE -- well inside
    // its next tick -- so the panel is back without waiting for it.
    let r = ask(&d, "lease_release", json!({ "token": token })).await;
    assert_eq!(r["restored"], json!("job"), "{r}");
    // Exactly ONE frame: the newest. A frame the widget queued during the
    // lease and that waited it out would land here too -- stale, and proof
    // the widget sat blocked on the queue instead of rendering on.
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(
        sent(&d).await - held,
        one_frame,
        "one frame repainted on release"
    );
    assert_eq!(job_kind(&d).await.as_deref(), Some("sysmon"));
    let _ = ask(&d, "live_job_stop", json!({ "mac": MAC, "kind": "sysmon" })).await;
}

#[tokio::test]
async fn an_unrenewed_lease_ends_itself_and_a_renewed_one_does_not() {
    let d = daemon().await;
    let mut rx = d.subscribe().expect("daemon broadcasts");
    let token = acquire(&d, 1_000).await;

    tokio::time::sleep(Duration::from_millis(600)).await;
    let r = ask(
        &d,
        "lease_renew",
        json!({ "token": token, "ttl_ms": 1_000 }),
    )
    .await;
    assert_eq!(r["success"], json!(true), "{r}");
    tokio::time::sleep(Duration::from_millis(700)).await;
    let r = call(&d, "show_image", None, frame(16)).await;
    assert_eq!(
        r["code"],
        json!("screen_leased"),
        "renewed at 600 ms, still held at 1.3 s: {r}"
    );

    // Nobody renews again: the holder may have crashed. The screen comes back.
    tokio::time::sleep(Duration::from_millis(900)).await;
    let r = call(&d, "show_image", None, frame(16)).await;
    assert_eq!(r["success"], json!(true), "expired, anyone draws: {r}");
    let r = ask(
        &d,
        "lease_renew",
        json!({ "token": token, "ttl_ms": 1_000 }),
    )
    .await;
    assert_eq!(r["code"], json!("lease_expired"), "{r}");

    let mut states = Vec::new();
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("lease") {
            states.push(ev["state"].as_str().unwrap_or("").to_string());
        }
    }
    assert_eq!(states, ["acquired", "expired"], "the bus says so");
}

#[tokio::test(flavor = "multi_thread")]
async fn leased_frames_conflate_on_a_slow_link() {
    // A slow link, simulated by a long item at the head of the panel's
    // queue: five frames queue up behind it. Each later frame replaces the
    // earlier ones whole, so only the newest is drawn.
    let d = daemon().await;
    let token = acquire(&d, 30_000).await;
    let queue = d
        .fleet
        .get(MAC)
        .await
        .expect("known")
        .link()
        .await
        .expect("linked")
        .queue
        .clone();
    let slow = queue.submit(
        Some(token.clone()),
        tokio::time::sleep(Duration::from_millis(400)),
    );

    let before = sent(&d).await;
    let calls: Vec<_> = (0..5)
        .map(|_| {
            let d = d.clone();
            let t = token.clone();
            tokio::spawn(async move { call(&d, "show_image", Some(&t), frame(16)).await })
        })
        .collect();
    let _ = slow.await;
    let mut drawn = 0;
    let mut skipped = 0;
    for c in calls {
        let r = c.await.expect("joined");
        assert_eq!(r["success"], json!(true), "{r}");
        if r["superseded"] == json!(true) {
            skipped += 1;
        } else {
            drawn += 1;
        }
    }
    assert_eq!((drawn, skipped), (1, 4), "latest frame wins");
    let one_frame = sent(&d).await - before;

    // Sequential pushes never overlap, so none is skipped.
    for _ in 0..3 {
        let r = call(&d, "show_image", Some(&token), frame(16)).await;
        assert_eq!(r["superseded"], Value::Null, "{r}");
    }
    assert_eq!(sent(&d).await - before, one_frame * 4);

    // The same holds with no lease at all: the GUI's pushes conflate too.
    let r = ask(&d, "lease_release", json!({ "token": token })).await;
    assert_eq!(r["success"], json!(true), "{r}");
    let slow = queue.submit(None, tokio::time::sleep(Duration::from_millis(400)));
    let calls: Vec<_> = (0..3)
        .map(|_| {
            let d = d.clone();
            tokio::spawn(async move { call(&d, "show_image", None, frame(16)).await })
        })
        .collect();
    let _ = slow.await;
    let mut superseded = 0;
    for c in calls {
        let r = c.await.expect("joined");
        assert_eq!(r["success"], json!(true), "{r}");
        superseded += usize::from(r["superseded"] == json!(true));
    }
    assert_eq!(superseded, 2, "unleased, latest frame wins as well");
}
