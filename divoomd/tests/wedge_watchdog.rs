//! The daemon notices its own wedge (P2.6).
//!
//! launchd has no watchdog and the protocol has no heartbeat, so a daemon whose
//! serving loop stopped turning (2026-09-07: five days deaf) was noticed by a
//! person, if at all. The detector lives in-process on its own OS thread and
//! is pinged from INSIDE the accept loop -- a side-channel probe would keep
//! succeeding while the loop it is meant to watch is stuck.
//!
//! The second test wedges the REAL `serve` loop: it runs on a current-thread
//! runtime, and the runtime is then blocked synchronously, which is exactly
//! what a blocking call on the serving thread does. The watchdog must fire
//! within its bound; while the loop is healthy (idle, no clients) it must not.

use std::sync::mpsc;
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tokio::net::UnixListener;

use divoomd::protocol::Request;
use divoomd::socket_server::{serve, Handler};
use divoomd::watchdog::{watch, Heartbeat};

const EVERY: Duration = Duration::from_millis(20);
const BOUND: Duration = Duration::from_millis(400);

struct Beats(Arc<Heartbeat>);

impl Handler for Beats {
    fn handle<'a>(
        &'a self,
        _req: Request,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Value> + Send + 'a>> {
        Box::pin(async move { json!({ "success": true }) })
    }
    fn heartbeat(&self) -> Option<Arc<Heartbeat>> {
        Some(self.0.clone())
    }
}

#[test]
fn a_heartbeat_that_never_beats_is_declared_wedged_within_the_bound() {
    let hb = Heartbeat::new(EVERY);
    let (tx, rx) = mpsc::channel();
    let started = Instant::now();
    let _w = watch(hb, BOUND, move |silence| {
        let _ = tx.send(silence);
    });
    let silence = rx.recv_timeout(BOUND * 4).expect("never declared wedged");
    assert!(silence >= BOUND, "declared early: {silence:?}");
    assert!(
        started.elapsed() < BOUND * 2,
        "declared late: {:?}",
        started.elapsed()
    );
}

#[test]
fn a_wedged_serving_loop_is_detected_and_a_healthy_idle_one_is_not() {
    let path = std::env::temp_dir().join(format!("divoomd_wedge_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    let hb = Heartbeat::new(EVERY);
    let (tx, rx) = mpsc::channel();
    let _w = watch(hb.clone(), BOUND, move |silence| {
        let _ = tx.send(silence);
    });

    rt.block_on(async {
        let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
        tokio::spawn(serve(
            listener,
            Arc::new(Beats(hb)),
            4,
            Duration::from_secs(60),
        ));
        // Idle and healthy for three bounds: no client ever connects, and the
        // loop must still prove it is turning.
        tokio::time::sleep(BOUND * 3).await;
    });
    assert!(
        rx.try_recv().is_err(),
        "an idle, healthy serving loop was declared wedged"
    );

    // Wedge it: block the only runtime thread, so the accept loop cannot run.
    let wedged_at = Instant::now();
    rt.block_on(async { std::thread::sleep(BOUND * 3) });
    let silence = rx
        .try_recv()
        .expect("the serving loop was wedged and nothing noticed");
    assert!(silence >= BOUND, "{silence:?}");
    assert!(wedged_at.elapsed() >= BOUND);
    let _ = std::fs::remove_file(&path);
}
