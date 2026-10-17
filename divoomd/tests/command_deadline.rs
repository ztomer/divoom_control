//! Every command runs under a deadline, so a stalled handler cannot hold its
//! connection forever (P2.3).
//!
//! `handler.handle(req).await` had no timeout: a command that never returned
//! pinned its connection permit for the life of the daemon, whether or not the
//! client was still there. Drives the real `serve` loop over a real unix socket
//! with a handler whose `stall` command never completes, and a one-connection
//! cap, so a held permit is directly visible as the NEXT client being refused.

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::net::{UnixListener, UnixStream};

use divoomd::protocol::{encode_message, Request};
use divoomd::socket_server::{serve, Handler};

mod ndjson;
use ndjson::next_line;

const BUDGET: Duration = Duration::from_millis(200);

struct Stalls;

impl Handler for Stalls {
    fn handle<'a>(
        &'a self,
        req: Request,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Value> + Send + 'a>> {
        Box::pin(async move {
            if req.command == "stall" {
                std::future::pending::<()>().await;
            }
            json!({ "success": true, "command": req.command })
        })
    }
    fn budget(&self, _req: &Request) -> Duration {
        BUDGET
    }
}

fn start(name: &str) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!("divoomd_{name}_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(
        listener,
        Arc::new(Stalls),
        1,
        Duration::from_secs(60),
    ));
    path
}

async fn ask(stream: &mut UnixStream, command: &str) -> Option<Value> {
    stream
        .write_all(&encode_message(&json!({ "command": command })))
        .await
        .ok()?;
    next_line(stream, Duration::from_secs(3)).await
}

#[tokio::test]
async fn a_stalled_command_is_answered_with_its_deadline() {
    let path = start("deadline_reply");
    let mut a = UnixStream::connect(&path).await.expect("connect");
    let reply = ask(&mut a, "stall")
        .await
        .expect("no reply: the stall held forever");
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(reply["code"], "deadline_exceeded", "{reply}");
    assert_eq!(reply["deadline_ms"], json!(200), "{reply}");
    // The connection is still usable: the deadline ended the command, not it.
    let next = ask(&mut a, "ping").await.expect("connection still served");
    assert_eq!(next["success"], json!(true), "{next}");
    let _ = std::fs::remove_file(&path);
}

#[tokio::test]
async fn a_client_that_left_a_stalled_command_frees_its_slot() {
    let path = start("deadline_slot");
    let mut a = UnixStream::connect(&path).await.expect("connect");
    a.write_all(&encode_message(&json!({ "command": "stall" })))
        .await
        .expect("write");
    drop(a); // gone; only the deadline can release the permit now
    tokio::time::sleep(BUDGET * 3).await;

    let mut b = UnixStream::connect(&path).await.expect("connect");
    let reply = ask(&mut b, "ping").await.expect("reply");
    assert_eq!(
        reply["success"],
        json!(true),
        "the one permit is still held by a command nobody is waiting for: {reply}"
    );
    let _ = std::fs::remove_file(&path);
}
