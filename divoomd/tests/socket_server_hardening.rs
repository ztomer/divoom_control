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
        Box::leak(Box::new(listener)),
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
async fn max_connections_backpressures_extra() {
    let path = temp_sock("max");
    let listener = UnixListener::bind(&path).unwrap();
    let handler = Arc::new(Stub);
    // max_connections = 1, long idle so the open connection keeps its permit.
    tokio::spawn(serve(
        Box::leak(Box::new(listener)),
        handler,
        1,
        Duration::from_secs(60),
    ));

    // Connection A occupies the single permit with a slow op.
    let mut a = UnixStream::connect(&path).await.unwrap();
    a.write_all(encode_message(&json!({ "command": "slow" })).as_slice())
        .await
        .unwrap();

    // Connection B arrives while the permit is held → back-pressured (no reply).
    let mut b = UnixStream::connect(&path).await.unwrap();
    b.write_all(encode_message(&json!({ "command": "ping" })).as_slice())
        .await
        .unwrap();
    let mut buf = [0u8; 256];
    let r = tokio::time::timeout(Duration::from_millis(300), b.read(&mut buf)).await;
    assert!(
        r.is_err(),
        "extra connection must be back-pressured (no reply within 300ms while permit is held)"
    );

    // A's slow op completes and it gets its reply.
    let n = tokio::time::timeout(Duration::from_secs(2), a.read(&mut buf))
        .await
        .expect("A should get a reply")
        .expect("A read should succeed");
    assert!(n > 0, "A should receive its reply after the slow op");
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
        Box::leak(Box::new(listener)),
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
