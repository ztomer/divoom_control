//! Slow-consumer hardening: a peer that stops READING must never pin the
//! resource it holds.
//!
//! Split out of `socket_server_hardening.rs` (500-line cap). These two tests are
//! one class in two places -- a subscriber pinning its registry slot, and a
//! request/reply client pinning its connection permit -- and both were live at
//! different times, so they belong side by side.
//!
//! NOTE: `serve` BORROWS its listener, and these harnesses `tokio::spawn` it,
//! which needs 'static -- so the listener is leaked for the life of the test
//! process. Deliberate, and bounded.

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;

use divoomd::protocol::{encode_message, Request};
use divoomd::socket_server::{serve, Handler};

/// Handler that supports `subscribe`; the test drives the broadcast itself.
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

/// Read one whole NDJSON line. A reply here is 64 KB, so a single `read` into a
/// fixed buffer returns a TRUNCATED line -- which parses as an error and reads
/// exactly like the server having failed. Frame properly or the test reports on
/// its own buffer size.
async fn read_line(stream: &mut UnixStream, limit: Duration) -> Option<Value> {
    let mut acc: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 8192];
    let deadline = tokio::time::Instant::now() + limit;
    loop {
        let left = deadline.checked_duration_since(tokio::time::Instant::now())?;
        let n = match tokio::time::timeout(left, stream.read(&mut chunk)).await {
            Ok(Ok(0)) | Err(_) => return None,
            Ok(Ok(n)) => n,
            Ok(Err(_)) => return None,
        };
        acc.extend_from_slice(&chunk[..n]);
        if let Some(i) = acc.iter().position(|b| *b == b'\n') {
            return serde_json::from_slice(&acc[..i]).ok();
        }
    }
}

/// Handler whose replies are large, so a client that stops reading fills the
/// socket buffer within a few of them.
struct BigReplyStub;
impl Handler for BigReplyStub {
    fn handle<'a>(
        &'a self,
        _req: Request,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Value> + Send + 'a>> {
        Box::pin(async move { json!({ "success": true, "pad": "x".repeat(64 * 1024) }) })
    }
}

/// A REQUEST/REPLY client that stops reading must not pin its connection slot.
///
/// The sibling of `a_subscriber_that_stops_reading_is_dropped_and_frees_its_slot`,
/// and the half that was still live: the write deadline had been applied by hand
/// to the two writes inside the subscriber `select!`, which left the ten other
/// `write_all` calls -- the whole request/reply path -- unbounded. A client that
/// pipelines requests and never reads the replies fills the socket buffer, the
/// reply write blocks forever, and the connection holds its permit for as long as
/// the process lives. At the cap that is the same total-deafness failure the
/// connection budget exists to prevent, reached one stuck client at a time.
///
/// Asserts the SLOT comes back, not merely that a write returned -- the permit is
/// the resource that was leaking.
#[tokio::test]
async fn a_request_client_that_stops_reading_frees_its_connection_slot() {
    let path = temp_sock("deafreq");
    let listener = UnixListener::bind(&path).unwrap();
    // Capacity 1: the deaf client holds the ONLY slot, so a second client is
    // refused for exactly as long as the first is not reclaimed.
    tokio::spawn(serve(
        Arc::new(listener),
        Arc::new(BigReplyStub),
        1,
        Duration::from_secs(120),
    ));

    // Pipeline enough requests that the replies cannot fit in the socket
    // buffer, then never read a byte.
    let mut deaf = UnixStream::connect(&path).await.unwrap();
    let mut pipelined = Vec::new();
    for _ in 0..64 {
        pipelined.extend_from_slice(encode_message(&json!({ "command": "ping" })).as_slice());
    }
    deaf.write_all(&pipelined).await.unwrap();

    // While it is stuck, the cap is full and a newcomer is refused. Proving the
    // refusal first is what makes the reclaim below mean something: without it a
    // pass could just mean the deaf client was never admitted at all.
    let mut refused = UnixStream::connect(&path).await.unwrap();
    refused
        .write_all(encode_message(&json!({ "command": "ping" })).as_slice())
        .await
        .unwrap();
    let v = read_line(&mut refused, Duration::from_secs(5))
        .await
        .expect("a full daemon must still answer");
    assert_eq!(v["code"], json!("resource_exhausted"), "got {v}");
    drop(refused);

    // The slot must come back once the write deadline expires. Under the
    // unbounded write it never did.
    let deadline = tokio::time::Instant::now() + Duration::from_secs(60);
    loop {
        assert!(
            tokio::time::Instant::now() < deadline,
            "the deaf request client never released its connection slot"
        );
        let mut fresh = UnixStream::connect(&path).await.unwrap();
        fresh
            .write_all(encode_message(&json!({ "command": "ping" })).as_slice())
            .await
            .unwrap();
        let Some(v) = read_line(&mut fresh, Duration::from_secs(5)).await else {
            continue;
        };
        if v["success"] == json!(true) {
            break; // served: the permit was reclaimed
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    let _ = std::fs::remove_file(&path);
    drop(deaf);
}
