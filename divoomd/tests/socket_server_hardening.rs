// NOTE: `serve` BORROWS its listener so the daemon can keep the socket's
// inode pinned until after its ownership check (see socket_owner). These
// harnesses `tokio::spawn` it, which needs 'static, so they leak the
// listener for the life of the test process -- deliberate, and bounded.
//! Socket-server hardening tests (R58): idle-timeout drops silent/dead peers, and
//! concurrent connections are capped (back-pressure) so a stuck client can't pin a
//! permit / the device lock forever. Drives the real `serve` loop with a stub
//! `Handler` over a real Unix socket — no device, no binary.

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;

use divoomd::protocol::{encode_message, Request};
use divoomd::socket_server::{serve, Handler};

struct Stub;

impl Handler for Stub {
    fn handle<'a>(
        &'a self,
        req: Request,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Value> + Send + 'a>> {
        Box::pin(async move {
            // "slow" hogs the connection's permit so a 2nd connection is
            // back-pressured for as long as this one stays open.
            if req.command == "slow" {
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
            json!({ "success": true, "command": req.command })
        })
    }
}

/// Handler that supports `subscribe` but never broadcasts an event. Used to prove
/// a silent subscriber is dropped by the idle watchdog.
struct SilentSubStub {
    tx: broadcast::Sender<Value>,
}
impl Handler for SilentSubStub {
    fn handle<'a>(
        &'a self,
        _req: Request,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Value> + Send + 'a>> {
        Box::pin(async move { json!({ "success": true }) })
    }
    fn subscribe(&self) -> Option<broadcast::Receiver<Value>> {
        Some(self.tx.subscribe())
    }
}

fn temp_sock(name: &str) -> std::path::PathBuf {
    let p = std::env::temp_dir().join(format!("divoomd_{name}_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&p);
    p
}

#[tokio::test]
async fn idle_timeout_drops_silent_peer() {
    let path = temp_sock("idle");
    let listener = UnixListener::bind(&path).unwrap();
    let handler = Arc::new(Stub);
    // 300ms idle: a peer that connects and sends nothing is dropped.
    tokio::spawn(serve(
        Arc::new(listener),
        handler,
        8,
        Duration::from_millis(300),
    ));

    let mut client = UnixStream::connect(&path).await.unwrap();
    let mut buf = [0u8; 64];
    // No bytes written → the daemon must close the socket within the idle window.
    let n = tokio::time::timeout(Duration::from_secs(2), client.read(&mut buf))
        .await
        .expect("idle timeout should close the peer within 2s")
        .expect("read should succeed (EOF)");
    assert_eq!(
        n, 0,
        "silent peer must be dropped (EOF) by the idle timeout"
    );
    let _ = std::fs::remove_file(&path);
}

#[tokio::test]
async fn at_capacity_the_daemon_answers_instead_of_going_silent() {
    // THE PROPERTY THAT ACTUALLY FAILED IN PRODUCTION. This test used to be
    // `max_connections_backpressures_extra`, and it asserted the OPPOSITE: that
    // the extra client gets NO reply within 300ms. That silence was the defect,
    // pinned as the specification.
    //
    // Reaching the cap stopped the accept loop, so the daemon went off the air
    // completely — no get_status, no health probe, nothing — while connect()
    // kept succeeding into the kernel backlog. A daemon sat like that for five
    // days (2026-09-07) and every diagnostic, including socket_bind's prober,
    // concluded another program owned the socket.
    //
    // A cap must bound work, never reachability. At capacity the daemon accepts
    // and refuses in one line.
    let path = temp_sock("cap");
    let listener = UnixListener::bind(&path).unwrap();
    tokio::spawn(serve(
        Arc::new(listener),
        Arc::new(Stub),
        1,
        Duration::from_secs(60),
    ));

    // A occupies the single slot and keeps it (its connection stays open).
    let mut a = UnixStream::connect(&path).await.unwrap();
    a.write_all(encode_message(&json!({ "command": "ping" })).as_slice())
        .await
        .unwrap();
    let mut buf = [0u8; 512];
    let n = tokio::time::timeout(Duration::from_secs(2), a.read(&mut buf))
        .await
        .expect("A should be served")
        .expect("A read should succeed");
    assert!(n > 0);

    // B arrives with the cap full: it must get an ANSWER, promptly.
    let mut b = UnixStream::connect(&path).await.unwrap();
    b.write_all(encode_message(&json!({ "command": "ping" })).as_slice())
        .await
        .unwrap();
    let n = tokio::time::timeout(Duration::from_secs(1), b.read(&mut buf))
        .await
        .expect("a daemon at capacity must still ANSWER — silence is the bug this replaced")
        .expect("B read should succeed");
    let reply: Value = serde_json::from_slice(&buf[..n])
        .unwrap_or_else(|e| panic!("refusal must be a parseable reply line: {e}"));
    assert_eq!(reply["success"], json!(false), "refusal says it failed");
    assert!(
        reply["error"]
            .as_str()
            .unwrap_or("")
            .contains("connection cap"),
        "the refusal must say WHY: {reply}"
    );

    // And it must still identify itself, or socket_bind's prober would read a
    // busy daemon as a foreign program and refuse to start a replacement.
    assert!(
        reply.get("daemon_version").is_some(),
        "a refusal must still carry the daemon identity marker: {reply}"
    );

    // A client must be able to branch on the refusal without string-matching
    // English prose, and must be told how long to bound its backoff. HTTP 503 +
    // Retry-After, gRPC RESOURCE_EXHAUSTED + grpc-retry-pushback-ms, SMTP 4yz.
    assert_eq!(reply["code"], json!("resource_exhausted"), "{reply}");
    assert!(
        reply["retry_after_ms"].as_u64().is_some_and(|ms| ms > 0),
        "a transient refusal must carry a positive retry bound: {reply}"
    );

    // Once A goes away the cap clears and service is normal again.
    drop(a);
    let mut c = UnixStream::connect(&path).await.unwrap();
    c.write_all(encode_message(&json!({ "command": "ping" })).as_slice())
        .await
        .unwrap();
    let n = tokio::time::timeout(Duration::from_secs(3), c.read(&mut buf))
        .await
        .expect("service must resume once a slot frees")
        .expect("C read should succeed");
    let reply: Value = serde_json::from_slice(&buf[..n]).unwrap();
    assert_eq!(reply["success"], json!(true), "C should be served normally");
    let _ = std::fs::remove_file(&path);
}

#[tokio::test]
async fn subscribe_idle_drops_silent_subscriber() {
    let path = temp_sock("subidle");
    let listener = UnixListener::bind(&path).unwrap();
    // A subscriber that never receives an event must be dropped by the idle
    // watchdog (so it can't pin a permit forever).
    let (tx, _rx) = broadcast::channel::<Value>(8);
    let handler = Arc::new(SilentSubStub { tx });
    tokio::spawn(serve(
        Arc::new(listener),
        handler,
        8,
        Duration::from_millis(300),
    ));

    let mut client = UnixStream::connect(&path).await.unwrap();
    client
        .write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
        .await
        .unwrap();

    // First read returns the initial status event.
    let mut buf = [0u8; 256];
    let n0 = tokio::time::timeout(Duration::from_secs(2), client.read(&mut buf))
        .await
        .expect("initial status should arrive")
        .expect("read should succeed");
    assert!(n0 > 0, "should receive the initial status event");

    // No further events → the connection is dropped (EOF) within the idle window.
    let n = tokio::time::timeout(Duration::from_secs(2), client.read(&mut buf))
        .await
        .expect("idle timeout should close the subscriber within 2s")
        .expect("read should succeed (EOF)");
    assert_eq!(
        n, 0,
        "silent subscriber must be dropped (EOF) by idle timeout"
    );
    let _ = std::fs::remove_file(&path);
}

/// Subscriptions have their own, smaller budget, so however many subscribers
/// accumulate the daemon can still take requests.
///
/// This is the structural half of the 2026-09-07 wedge. Request/reply clients
/// close as soon as they have their answer, so the only connections that can
/// pile up are subscriptions — and with one shared budget, enough of them made
/// the daemon unable to answer anything at all. Separate budgets make that
/// arithmetically impossible.
#[tokio::test]
async fn subscribers_cannot_starve_request_handling() {
    let path = temp_sock("subbudget");
    let listener = UnixListener::bind(&path).unwrap();
    let (tx, _rx) = broadcast::channel::<Value>(8);
    // max_connections = 4 → subscription budget = 4/2 = 2, so two connection
    // slots are always reserved for requests. Long idle so nothing is reaped
    // underneath the assertions.
    tokio::spawn(serve(
        Arc::new(listener),
        Arc::new(SilentSubStub { tx }),
        4,
        Duration::from_secs(60),
    ));

    // Fill the subscription budget.
    let mut subs = Vec::new();
    let mut buf = [0u8; 512];
    for i in 0..2 {
        let mut s = UnixStream::connect(&path).await.unwrap();
        s.write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
            .await
            .unwrap();
        let n = tokio::time::timeout(Duration::from_secs(2), s.read(&mut buf))
            .await
            .unwrap_or_else(|_| panic!("subscriber {i} got no initial status"))
            .unwrap();
        let v: Value = serde_json::from_slice(&buf[..n]).unwrap();
        assert_eq!(v["type"], json!("status"), "subscriber {i}: {v}");
        subs.push(s);
    }

    // A 3rd subscribe is refused with a REASON, not silence...
    let mut extra = UnixStream::connect(&path).await.unwrap();
    extra
        .write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
        .await
        .unwrap();
    let n = tokio::time::timeout(Duration::from_secs(2), extra.read(&mut buf))
        .await
        .expect("an over-budget subscriber must be told, not hung")
        .unwrap();
    let v: Value = serde_json::from_slice(&buf[..n]).unwrap();
    assert_eq!(v["success"], json!(false), "{v}");
    assert!(
        v["error"].as_str().unwrap_or("").contains("subscriptions"),
        "the refusal must say what ran out: {v}"
    );

    // ...and that same connection can still issue ordinary requests. This is the
    // property the old single-budget design lost entirely.
    extra
        .write_all(encode_message(&json!({ "command": "ping" })).as_slice())
        .await
        .unwrap();
    let n = tokio::time::timeout(Duration::from_secs(2), extra.read(&mut buf))
        .await
        .expect("requests must still be served while every subscription slot is taken")
        .unwrap();
    let v: Value = serde_json::from_slice(&buf[..n]).unwrap();
    assert_eq!(v["success"], json!(true), "{v}");

    let _ = std::fs::remove_file(&path);
}

/// A quiet subscription's slot is reclaimed for a newcomer, and the client is
/// told to reconnect — while a subscription whose client has SPOKEN is left
/// alone. Nothing is disturbed until a slot is actually needed.
///
/// This replaced a blanket max-age that renegotiated every subscription on a
/// timer: churn charged to healthy clients to solve a problem caused by dead
/// ones. It also replaced the original watchdog, which reset on every event the
/// daemon DELIVERED — a broadcast, so it moved every subscriber's clock in
/// lockstep and could never tell a live client from a dead one.
#[tokio::test]
async fn a_quiet_subscription_yields_its_slot_and_an_active_one_keeps_it() {
    let path = temp_sock("lru");
    let listener = UnixListener::bind(&path).unwrap();
    let (tx, _rx) = broadcast::channel::<Value>(16);
    // max_connections 4 → subscription budget 2. Long idle so only the LRU
    // policy can end anything here.
    tokio::spawn(serve(
        Arc::new(listener),
        Arc::new(SilentSubStub { tx }),
        4,
        Duration::from_secs(120),
    ));

    async fn subscribe(path: &std::path::Path) -> UnixStream {
        let mut s = UnixStream::connect(path).await.unwrap();
        s.write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
            .await
            .unwrap();
        let mut buf = [0u8; 512];
        let n = tokio::time::timeout(Duration::from_secs(2), s.read(&mut buf))
            .await
            .expect("initial status")
            .unwrap();
        let v: Value = serde_json::from_slice(&buf[..n]).unwrap();
        assert_eq!(v["type"], json!("status"));
        s
    }

    let mut quiet = subscribe(&path).await;
    let mut busy = subscribe(&path).await;

    // The busy client proves it is there. The quiet one never says a word.
    busy.write_all(b"{\"command\":\"ping\"}\n").await.unwrap();
    tokio::time::sleep(Duration::from_millis(200)).await;

    // A third client needs a slot. RENEGOTIATE_AFTER is 10 minutes in
    // production, so nothing is stale yet: the newcomer must be REFUSED rather
    // than allowed to evict a live client.
    let mut third = UnixStream::connect(&path).await.unwrap();
    third
        .write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
        .await
        .unwrap();
    let mut buf = [0u8; 512];
    let n = tokio::time::timeout(Duration::from_secs(2), third.read(&mut buf))
        .await
        .expect("the newcomer must be answered, not hung")
        .unwrap();
    let v: Value = serde_json::from_slice(&buf[..n]).unwrap();
    assert_eq!(v["success"], json!(false), "{v}");
    assert!(
        v["error"].as_str().unwrap_or("").contains("subscriptions"),
        "refusal must name what ran out: {v}"
    );

    // And neither incumbent was disturbed: no resubscribe notice, no close.
    for (name, s) in [("quiet", &mut quiet), ("busy", &mut busy)] {
        assert!(
            tokio::time::timeout(Duration::from_millis(200), s.read(&mut buf))
                .await
                .is_err(),
            "{name} subscriber must be left alone while slots are not stale"
        );
    }
    let _ = std::fs::remove_file(&path);
}

/// A subscriber that stops READING is disconnected, and cannot pin its slot.
///
/// This is the residual half of the 2026-09-07 wedge, found by a literature
/// survey after the registry shipped. A non-reading peer is not idle (we have
/// events for it) and has not closed (no EOF); its socket buffer absorbs writes
/// until it fills, after which `write_all` blocks forever. Because the body of a
/// chosen `select!` arm runs to completion, that stall makes the eviction arm,
/// the idle deadline and the read arm all unreachable — so the subscriber holds
/// its registry slot permanently and cannot be reclaimed.
///
/// The fix is a write deadline then disconnect, which is what NATS and Redis
/// both do with a slow consumer. The test proves the SLOT comes back, which is
/// the property that failed, not merely that the write returned.
#[tokio::test]
async fn a_subscriber_that_stops_reading_is_dropped_and_frees_its_slot() {
    let path = temp_sock("noread");
    let listener = UnixListener::bind(&path).unwrap();
    let (tx, _rx) = broadcast::channel::<Value>(4);
    let feed = tx.clone();
    // Capacity 2 -> subscription budget 1, so the stalled subscriber holds the
    // ONLY slot: if it is never reclaimed, nobody else can ever subscribe.
    tokio::spawn(serve(
        Arc::new(listener),
        Arc::new(SilentSubStub { tx }),
        2,
        Duration::from_secs(120),
    ));

    let mut deaf = UnixStream::connect(&path).await.unwrap();
    deaf.write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
        .await
        .unwrap();
    // Read ONLY the initial status, then never again.
    let mut buf = [0u8; 256];
    let n = tokio::time::timeout(Duration::from_secs(2), deaf.read(&mut buf))
        .await
        .expect("initial status")
        .unwrap();
    assert!(n > 0);

    // Push enough traffic to fill the socket buffer and stall the write.
    tokio::spawn(async move {
        let payload = "x".repeat(4096);
        for i in 0..20_000 {
            if feed
                .send(json!({ "type": "tick", "i": i, "pad": payload }))
                .is_err()
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    });

    // The slot must come back: a fresh client can subscribe. Under the old code
    // the stalled task held it forever and this timed out.
    let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
    loop {
        assert!(
            tokio::time::Instant::now() < deadline,
            "the stalled subscriber never released its slot"
        );
        let mut fresh = UnixStream::connect(&path).await.unwrap();
        fresh
            .write_all(encode_message(&json!({ "command": "subscribe" })).as_slice())
            .await
            .unwrap();
        let n = match tokio::time::timeout(Duration::from_secs(2), fresh.read(&mut buf)).await {
            Ok(Ok(n)) if n > 0 => n,
            _ => continue,
        };
        let v: Value = serde_json::from_slice(&buf[..n]).unwrap();
        if v["type"] == json!("status") {
            break; // slot reclaimed, we are subscribed
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    let _ = std::fs::remove_file(&path);
    drop(deaf);
}
