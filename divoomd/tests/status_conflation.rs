//! A slow status subscriber gets the latest state for every key it missed,
//! not a hole and not a disconnect (P2.5).
//!
//! Subscribers share a 32-slot broadcast ring; one that fell behind was sent
//! `{"type":"lagged"}` notices and dropped past 64 lost events. A status
//! subscriber wants the CURRENT truth, so the server now resynchronises it
//! from the latest value of each key. Drives the real `serve` loop: one reader
//! stalls (reads nothing) while hundreds of updates to three keys go past,
//! then reads, and must end on the newest value of each key, with no gap
//! notice, and still be connected.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;

use divoomd::events::Events;
use divoomd::protocol::{encode_message, Request};
use divoomd::socket_server::{serve, Handler};

mod ndjson;
use ndjson::next_line;

struct Bus(Arc<Events>);

impl Handler for Bus {
    fn handle<'a>(
        &'a self,
        _req: Request,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Value> + Send + 'a>> {
        Box::pin(async move { json!({ "success": true }) })
    }
    fn subscribe(&self) -> Option<broadcast::Receiver<Value>> {
        Some(self.0.subscribe())
    }
    fn events(&self) -> Option<Arc<Events>> {
        Some(self.0.clone())
    }
}

const UPDATES: u64 = 400;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_stalled_reader_catches_up_to_the_latest_value_of_every_key() {
    let path = std::env::temp_dir().join(format!("divoomd_conflate_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let bus = Events::new(divoomd::events::RING);
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(
        listener,
        Arc::new(Bus(bus.clone())),
        8,
        Duration::from_secs(60),
    ));

    let mut slow = UnixStream::connect(&path).await.expect("connect");
    slow.write_all(&encode_message(&json!({ "command": "subscribe" })))
        .await
        .expect("write");
    let first = next_line(&mut slow, Duration::from_secs(3))
        .await
        .expect("initial");
    assert_eq!(first["type"], "status");

    // Stall: read nothing while every key is updated hundreds of times. The
    // padding fills the socket buffer, so the server's pump blocks on its
    // write and the ring laps it many times over.
    let pad = "x".repeat(2048);
    for n in 0..UPDATES {
        for mac in ["A", "B"] {
            let _ = bus.send(json!({ "type": "status", "mac": mac, "n": n, "pad": pad }));
        }
        let _ = bus.send(json!({ "type": "selection", "mac": "A", "n": n }));
        tokio::task::yield_now().await;
    }
    tokio::time::sleep(Duration::from_millis(500)).await;

    // Now read everything there is. The last value seen per key must be the
    // newest one published, and nothing may say there was a hole.
    let mut last: HashMap<String, u64> = HashMap::new();
    while let Some(ev) = next_line(&mut slow, Duration::from_millis(1500)).await {
        assert_ne!(ev["type"], "lagged", "a hole, not the latest state: {ev}");
        assert_ne!(ev["type"], "resubscribe", "dropped instead of caught up");
        if let Some(n) = ev["n"].as_u64() {
            last.insert(Events::key(&ev), n);
        }
    }
    for key in ["status|A", "status|B", "selection|A"] {
        assert_eq!(
            last.get(key),
            Some(&(UPDATES - 1)),
            "{key} did not end on its latest value: {last:?}"
        );
    }

    // Still subscribed: a fresh update arrives.
    let _ = bus.send(json!({ "type": "status", "mac": "A", "n": UPDATES }));
    let ev = next_line(&mut slow, Duration::from_secs(3))
        .await
        .expect("disconnected instead of conflated");
    assert_eq!(ev["n"], json!(UPDATES), "{ev}");
    let _ = std::fs::remove_file(&path);
}
