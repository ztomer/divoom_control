//! A reconnecting subscriber replaces its own slot (P2.4).
//!
//! The registry keyed entries by a counter, so a client that crashed and came
//! back was a stranger: refused while every slot had been active within 600 s.
//! Fills the real server's subscription budget, then reconnects one client by
//! name while its old connection is still open (the daemon has not yet seen it
//! die): the reconnect is admitted at once, the old connection is told why it
//! was closed, and an anonymous newcomer is still refused.

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;

use divoomd::protocol::{encode_message, Request};
use divoomd::socket_server::{serve, Handler};

mod ndjson;
use ndjson::next_line;

const LINE: Duration = Duration::from_secs(3);

struct Subs {
    tx: broadcast::Sender<Value>,
}

impl Handler for Subs {
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

async fn subscribe(path: &std::path::Path, client_id: Option<&str>) -> (UnixStream, Value) {
    let mut s = UnixStream::connect(path).await.expect("connect");
    let mut req = json!({ "command": "subscribe" });
    if let Some(id) = client_id {
        req["args"] = json!({ "client_id": id });
    }
    s.write_all(&encode_message(&req)).await.expect("write");
    let first = next_line(&mut s, LINE).await.expect("a first line");
    (s, first)
}

#[tokio::test]
async fn a_named_reconnect_takes_its_slot_back_from_a_full_registry() {
    let path = std::env::temp_dir().join(format!("divoomd_takeover_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let (tx, _) = broadcast::channel(8);
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    // 4 connections -> a subscription budget of 2.
    tokio::spawn(serve(
        listener,
        Arc::new(Subs { tx }),
        4,
        Duration::from_secs(60),
    ));

    let (mut gui, first) = subscribe(&path, Some("divoom-gui")).await;
    assert_eq!(first["type"], "status", "{first}");
    let (_bar, first) = subscribe(&path, Some("divoom-menubar")).await;
    assert_eq!(first["type"], "status", "{first}");
    let (_anon, refused) = subscribe(&path, None).await;
    assert_eq!(
        refused["success"],
        json!(false),
        "the budget is full: {refused}"
    );

    let (_gui2, first) = subscribe(&path, Some("divoom-gui")).await;
    assert_eq!(
        first["type"], "status",
        "a named reconnect must be admitted at once, not refused: {first}"
    );
    let notice = next_line(&mut gui, LINE)
        .await
        .expect("the replaced connection is told why");
    assert_eq!(notice["type"], "resubscribe", "{notice}");
    assert_eq!(notice["code"], "taken_over", "{notice}");
    assert!(next_line(&mut gui, LINE).await.is_none(), "and then closed");

    let (_late, refused) = subscribe(&path, Some("someone-else")).await;
    assert_eq!(
        refused["success"],
        json!(false),
        "the takeover replaced a slot, it did not add one: {refused}"
    );
    let _ = std::fs::remove_file(&path);
}
