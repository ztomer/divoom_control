//! `get_status` says who is connected (P2.2).
//!
//! The 2026-09-07 wedge held all 64 connection permits and its cause was never
//! found, because the only way to look was to kill the daemon. These drive the
//! REAL accept loop with the REAL daemon over a real unix socket, open
//! connections of both kinds, and read them back through `get_status` -- the
//! question a wedged daemon must be able to answer without being killed.

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::net::{UnixListener, UnixStream};

use divoomd::daemon::Daemon;
use divoomd::protocol::encode_message;
use divoomd::socket_server::serve;

mod ndjson;
use ndjson::next_line;

const LINE: Duration = Duration::from_secs(5);

fn temp_sock(name: &str) -> std::path::PathBuf {
    let p = std::env::temp_dir().join(format!("divoomd_{name}_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&p);
    p
}

async fn send(stream: &mut UnixStream, command: &str) {
    stream
        .write_all(&encode_message(&json!({ "command": command })))
        .await
        .expect("write");
}

fn of_kind<'a>(open: &'a [Value], kind: &str) -> Vec<&'a Value> {
    open.iter().filter(|c| c["kind"] == kind).collect()
}

#[tokio::test]
async fn get_status_reports_connections_by_kind_with_ages() {
    const REQUESTS: usize = 3;
    const SUBSCRIPTIONS: usize = 2;
    let path = temp_sock("census");
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(
        listener,
        Arc::new(Daemon::new()),
        16,
        Duration::from_secs(60),
    ));

    // Idle request connections: accepted, holding a slot, saying nothing.
    let mut idle = Vec::new();
    for _ in 0..REQUESTS {
        idle.push(UnixStream::connect(&path).await.expect("connect"));
    }
    let mut subs = Vec::new();
    for _ in 0..SUBSCRIPTIONS {
        let mut s = UnixStream::connect(&path).await.expect("connect");
        send(&mut s, "subscribe").await;
        let first = next_line(&mut s, LINE).await.expect("initial status");
        assert_eq!(first["type"], "status", "subscription refused: {first}");
        subs.push(s);
    }
    let held_for = Duration::from_millis(250);
    tokio::time::sleep(held_for).await;

    let mut q = UnixStream::connect(&path).await.expect("connect");
    send(&mut q, "get_status").await;
    let reply = next_line(&mut q, LINE).await.expect("get_status reply");
    let conns = &reply["connections"];
    assert!(
        conns.is_object(),
        "get_status has no connection census: {reply}"
    );

    // The asking connection is itself an open request.
    assert_eq!(conns["counts"]["request"], json!(REQUESTS + 1), "{conns}");
    assert_eq!(
        conns["counts"]["subscription"],
        json!(SUBSCRIPTIONS),
        "{conns}"
    );
    assert_eq!(
        conns["limits"]["unix"],
        json!({ "connections": 16, "subscriptions": 8 })
    );

    let open = conns["open"].as_array().expect("open is a list");
    let me = i64::from(std::process::id().cast_signed());
    let floor = u64::try_from(held_for.as_millis()).expect("small");
    for c in of_kind(open, "subscription") {
        assert!(
            c["age_ms"].as_u64().expect("age") >= floor,
            "too young: {c}"
        );
        assert_eq!(c["pid"].as_i64(), Some(me), "peer pid not read: {c}");
        assert_eq!(c["transport"], "unix");
    }
    let requests = of_kind(open, "request");
    let silent = requests.iter().filter(|c| c["command"].is_null()).count();
    assert_eq!(
        silent, REQUESTS,
        "idle requests must show no command: {conns}"
    );
    let asking = requests
        .iter()
        .filter(|c| c["command"] == "get_status")
        .count();
    assert_eq!(asking, 1, "the in-flight get_status must be named: {conns}");
    for c in requests.iter().filter(|c| c["command"].is_null()) {
        assert!(c["idle_ms"].as_u64().expect("idle") >= floor, "{c}");
    }

    // Closing connections takes them out of the table.
    drop(idle);
    drop(subs);
    tokio::time::sleep(Duration::from_millis(100)).await;
    send(&mut q, "get_status").await;
    let after = next_line(&mut q, LINE).await.expect("second reply");
    assert_eq!(
        after["connections"]["counts"],
        json!({ "request": 1, "subscription": 0 }),
        "{after}"
    );
    let _ = std::fs::remove_file(&path);
}
