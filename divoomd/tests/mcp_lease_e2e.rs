//! An agent borrows a panel over MCP and gives it back (P4.6), end to end.
//!
//! Phase 4's exit, as a test: the real `divoomd mcp` binary, as an MCP
//! client's config launches it, against a real daemon on a unix socket with a
//! mock 64x64 panel running a live widget. The agent leases the screen and
//! plays a full-resolution, multi-frame animation on it; a second caller is
//! refused; then the agent stops renewing -- as a crashed agent would -- and
//! the panel goes back to its widget without anyone's help.

use std::io::Cursor;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::{serve, Handler};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixListener;
use tokio::process::{ChildStdin, ChildStdout, Command};

const MAC: &str = "MCP_LEASE";

struct Mcp {
    stdin: ChildStdin,
    stdout: tokio::io::Lines<BufReader<ChildStdout>>,
    id: u64,
}

impl Mcp {
    async fn call(&mut self, name: &str, arguments: Value) -> (bool, Value) {
        self.id += 1;
        let req = json!({ "jsonrpc": "2.0", "id": self.id, "method": "tools/call",
                          "params": { "name": name, "arguments": arguments } });
        let mut line = serde_json::to_vec(&req).expect("json");
        line.push(b'\n');
        self.stdin.write_all(&line).await.expect("write");
        let reply = tokio::time::timeout(Duration::from_secs(10), self.stdout.next_line())
            .await
            .expect("an answer in time")
            .expect("read")
            .expect("a line");
        let reply: Value = serde_json::from_str(&reply).expect("json reply");
        let result = &reply["result"];
        let text = result["content"][0]["text"].as_str().expect("text content");
        (
            result["isError"] == json!(true),
            serde_json::from_str(text).expect("tool json"),
        )
    }
}

/// A two-frame 64x64 GIF: red, then blue, 100 ms each.
fn two_frame_gif() -> String {
    let mut out = Cursor::new(Vec::new());
    {
        let mut enc = image::codecs::gif::GifEncoder::new(&mut out);
        for rgb in [[255, 0, 0], [0, 0, 255]] {
            let img =
                image::RgbaImage::from_pixel(64, 64, image::Rgba([rgb[0], rgb[1], rgb[2], 255]));
            let frame =
                image::Frame::from_parts(img, 0, 0, image::Delay::from_numer_denom_ms(100, 1));
            enc.encode_frame(frame).expect("gif frame");
        }
    }
    base64::engine::general_purpose::STANDARD.encode(out.into_inner())
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

async fn assert_mcp_discovery(mcp: &mut Mcp) {
    let (bad, cap) = mcp.call("get_capabilities", json!({ "mac": MAC })).await;
    assert!(!bad, "get_capabilities answers: {cap}");
    assert_eq!(cap["model"], json!("Pixoo64Wifi"), "{cap}");
    assert_eq!(cap["width"], json!(64), "{cap}");
    assert_eq!(cap["height"], json!(64), "{cap}");
    assert_eq!(cap["model_source"], json!("name"), "{cap}");
    assert_eq!(cap["chassis"]["family"], json!("pixoo64"), "{cap}");
    assert_eq!(cap["features"]["wifi"], json!(true), "{cap}");
    assert_eq!(cap["features"]["speaker"], json!(false), "{cap}");
    assert_eq!(cap["features"]["radio"], json!(false), "{cap}");
    let screens = cap["screens"].as_array().expect("the app's home list");
    assert!(!screens.iter().any(|s| s == "fm_radio"), "{screens:?}");
    let (bad, listed) = mcp.call("list_screens", json!({})).await;
    assert!(!bad, "list_screens answers: {listed}");
    let listed = listed["screens"]
        .as_array()
        .and_then(|s| {
            s.iter()
                .find(|e| e["mac"].as_str().is_some_and(|m| m == MAC))
        })
        .expect("the mock panel is listed");
    assert_eq!(listed["connected"], json!(true), "{listed}");
    assert_eq!(listed["width"], json!(64), "{listed}");
    assert_eq!(
        listed["chassis"]["family"],
        json!("pixoo64"),
        "each screen carries its kind too: {listed}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn an_agent_leases_draws_and_a_lapsed_lease_hands_the_panel_back() {
    let path = std::env::temp_dir().join(format!("divoomd_mcp_lease_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let ask = |c: &str, a: Value| d.handle(make_request(c, Some(a), None));
    assert_eq!(
        ask(
            "connect",
            json!({ "mock": true, "mac": MAC, "name": "Pixoo64-light" })
        )
        .await["success"],
        json!(true)
    );
    let job = ask(
        "live_job_start",
        json!({ "mac": MAC, "kind": "sysmon", "params": { "size": 64 } }),
    )
    .await;
    assert_eq!(job["success"], json!(true), "{job}");
    let mut events = d.subscribe().expect("the daemon broadcasts");
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(listener, d.clone(), 8, Duration::from_secs(60)));

    let mut child = Command::new(env!("CARGO_BIN_EXE_divoomd"))
        .arg("mcp")
        .env("DIVOOM_SOCKET", &path)
        .env_remove("DIVOOM_DAEMON_HOST")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .expect("divoomd mcp starts");
    let mut mcp = Mcp {
        stdin: child.stdin.take().expect("stdin"),
        stdout: BufReader::new(child.stdout.take().expect("stdout")).lines(),
        id: 0,
    };

    assert_mcp_discovery(&mut mcp).await;

    let (bad, lease) = mcp
        .call(
            "lease_acquire",
            json!({ "mac": MAC, "ttl_ms": 1500, "holder": "e2e agent" }),
        )
        .await;
    assert!(!bad, "{lease}");
    let token = lease["lease"].as_str().expect("a lease token").to_string();

    let before = sent(&d).await;
    let (bad, drawn) = mcp
        .call(
            "push_animation",
            json!({ "mac": MAC, "data": two_frame_gif(), "lease": token }),
        )
        .await;
    assert!(!bad, "the holder draws: {drawn}");
    assert_eq!(
        (drawn["size"].as_u64(), drawn["frames"].as_u64()),
        (Some(64), Some(2)),
        "full resolution, every frame: {drawn}"
    );
    assert!(sent(&d).await > before, "the animation reached the panel");
    let (bad, refused) = mcp
        .call("show_text", json!({ "mac": MAC, "text": "No", "size": 16 }))
        .await;
    assert!(bad, "a caller without the lease is refused: {refused}");
    assert!(
        refused["error"]
            .as_str()
            .is_some_and(|e| e.contains("e2e agent")),
        "and told who holds it: {refused}"
    );
    let still = d.fleet.get(MAC).await.expect("known").live_kind().await;
    assert_eq!(
        still.as_deref(),
        Some("sysmon"),
        "the widget was paused, not stopped"
    );

    // The agent goes quiet. Within its TTL plus a margin, the lease ends and
    // the widget's frame is back on the panel.
    let deadline = tokio::time::Instant::now() + Duration::from_secs(4);
    let mut ended = None;
    while ended.is_none() && tokio::time::Instant::now() < deadline {
        if let Ok(Ok(ev)) = tokio::time::timeout(Duration::from_millis(100), events.recv()).await {
            if ev["type"] == json!("lease") && ev["state"] == json!("expired") {
                ended = Some(ev);
            }
        }
    }
    let ended = ended.expect("the lapsed lease ended by itself");
    assert_eq!(ended["restored"], json!("job"), "{ended}");
    let (bad, after) = mcp
        .call("lease_renew", json!({ "lease": token, "ttl_ms": 1500 }))
        .await;
    assert!(bad, "a lapsed lease cannot be renewed: {after}");
    let (bad, free) = mcp
        .call("show_text", json!({ "mac": MAC, "text": "Ok", "size": 16 }))
        .await;
    assert!(!bad, "the panel is free again: {free}");

    drop(mcp);
    let _ = child.wait().await;
    let _ = std::fs::remove_file(&path);
}
