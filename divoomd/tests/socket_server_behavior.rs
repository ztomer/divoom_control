//! End-to-end socket-server behavior over a real unix socket, in-process: a client
//! connects, sends NDJSON requests, and reads NDJSON replies. Proves the
//! request/reply transport works independently of any device (hardware-free).

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use divoomd::protocol::{encode_message, iter_messages, make_request, Request};
use divoomd::socket_server::{serve, Handler, CONNECTION_IDLE_TIMEOUT, MAX_CONNECTIONS};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{UnixListener, UnixStream};

/// Stub handler: echoes the command back, and surfaces args/token so the test can
/// assert the request was parsed correctly.
struct Echo {
    tx: tokio::sync::broadcast::Sender<Value>,
}
impl Echo {
    fn new() -> Self {
        let (tx, _) = tokio::sync::broadcast::channel(10);
        Echo { tx }
    }
}
impl Handler for Echo {
    fn handle<'a>(&'a self, req: Request) -> Pin<Box<dyn Future<Output = Value> + Send + 'a>> {
        Box::pin(async move {
            json!({
                "success": true,
                "echo": req.command,
                "args": req.args,
                "token": req.token,
            })
        })
    }
    fn subscribe(&self) -> Option<tokio::sync::broadcast::Receiver<Value>> {
        Some(self.tx.subscribe())
    }
}

fn temp_sock(tag: &str) -> std::path::PathBuf {
    // short path (macOS unix-socket paths are limited to ~104 bytes)
    std::env::temp_dir().join(format!("divoomd_{}_{}.sock", tag, std::process::id()))
}

async fn read_one_line(stream: &mut UnixStream) -> Vec<u8> {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 1024];
    loop {
        let n = stream.read(&mut tmp).await.unwrap();
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&tmp[..n]);
        if buf.contains(&b'\n') {
            break;
        }
    }
    buf
}

#[tokio::test(flavor = "multi_thread")]
async fn request_reply_round_trip() {
    let path = temp_sock("rr");
    let _ = std::fs::remove_file(&path);
    let listener = UnixListener::bind(&path).unwrap();
    tokio::spawn(serve(
        listener,
        Arc::new(Echo::new()),
        MAX_CONNECTIONS,
        CONNECTION_IDLE_TIMEOUT,
    ));

    let mut client = UnixStream::connect(&path).await.unwrap();
    let req = make_request("scan", Some(json!({"timeout": 5})), Some("tok".into()));
    client
        .write_all(&encode_message(&serde_json::to_value(&req).unwrap()))
        .await
        .unwrap();

    let line = read_one_line(&mut client).await;
    let (msgs, _rem) = iter_messages(&line);
    assert_eq!(msgs.len(), 1);
    assert_eq!(
        msgs[0],
        json!({"success": true, "echo": "scan", "args": {"timeout": 5}, "token": "tok"})
    );

    let _ = std::fs::remove_file(&path);
}

#[tokio::test(flavor = "multi_thread")]
async fn two_pipelined_requests_get_two_replies() {
    let path = temp_sock("pipe");
    let _ = std::fs::remove_file(&path);
    let listener = UnixListener::bind(&path).unwrap();
    tokio::spawn(serve(
        listener,
        Arc::new(Echo::new()),
        MAX_CONNECTIONS,
        CONNECTION_IDLE_TIMEOUT,
    ));

    let mut client = UnixStream::connect(&path).await.unwrap();
    // send two requests back-to-back in one write
    let mut payload = encode_message(&serde_json::to_value(make_request("a", None, None)).unwrap());
    payload.extend(encode_message(
        &serde_json::to_value(make_request("b", None, None)).unwrap(),
    ));
    client.write_all(&payload).await.unwrap();

    // read until we have two newline-terminated lines
    let mut buf = Vec::new();
    let mut tmp = [0u8; 1024];
    while buf.iter().filter(|&&b| b == b'\n').count() < 2 {
        let n = client.read(&mut tmp).await.unwrap();
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&tmp[..n]);
    }
    let (msgs, _rem) = iter_messages(&buf);
    assert_eq!(msgs.len(), 2);
    assert_eq!(msgs[0]["echo"], json!("a"));
    assert_eq!(msgs[1]["echo"], json!("b"));

    let _ = std::fs::remove_file(&path);
}

#[tokio::test(flavor = "multi_thread")]
async fn malformed_line_gets_error_reply() {
    let path = temp_sock("bad");
    let _ = std::fs::remove_file(&path);
    let listener = UnixListener::bind(&path).unwrap();
    tokio::spawn(serve(
        listener,
        Arc::new(Echo::new()),
        MAX_CONNECTIONS,
        CONNECTION_IDLE_TIMEOUT,
    ));

    let mut client = UnixStream::connect(&path).await.unwrap();
    // valid JSON but not a Request (no "command") -> error reply, connection stays up
    client
        .write_all(b"{\"not\":\"a request\"}\n")
        .await
        .unwrap();
    let line = read_one_line(&mut client).await;
    let (msgs, _rem) = iter_messages(&line);
    assert_eq!(msgs[0]["success"], json!(false));
    assert!(msgs[0]["error"].as_str().unwrap().contains("bad request"));

    let _ = std::fs::remove_file(&path);
}

#[tokio::test(flavor = "multi_thread")]
async fn subscription_and_event_broadcast() {
    let path = temp_sock("sub");
    let _ = std::fs::remove_file(&path);
    let listener = UnixListener::bind(&path).unwrap();
    let handler = Arc::new(Echo::new());
    tokio::spawn(serve(
        listener,
        handler.clone(),
        MAX_CONNECTIONS,
        CONNECTION_IDLE_TIMEOUT,
    ));

    let mut client = UnixStream::connect(&path).await.unwrap();
    let req = make_request("subscribe", None, None);
    client
        .write_all(&encode_message(&serde_json::to_value(&req).unwrap()))
        .await
        .unwrap();

    // 1. Initial status event
    let line = read_one_line(&mut client).await;
    let (msgs, _rem) = iter_messages(&line);
    assert_eq!(msgs.len(), 1);
    assert_eq!(msgs[0]["type"], json!("status"));
    assert_eq!(msgs[0]["state"], json!("idle"));

    // 2. Broadcast a custom event
    let event = json!({
        "type": "notification",
        "app_type": 1,
        "title": "Hello",
        "body": "World"
    });
    handler.tx.send(event.clone()).unwrap();

    // Read the broadcast event
    let line2 = read_one_line(&mut client).await;
    let (msgs2, _rem) = iter_messages(&line2);
    assert_eq!(msgs2.len(), 1);
    assert_eq!(msgs2[0], event);

    let _ = std::fs::remove_file(&path);
}
