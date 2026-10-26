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
    async fn send(&mut self, msg: &Value) {
        let mut line = serde_json::to_vec(msg).expect("json");
        line.push(b'\n');
        self.stdin.write_all(&line).await.expect("write");
    }

    async fn request(&mut self, method: &str, params: Value) -> Value {
        self.id += 1;
        let req = json!({ "jsonrpc": "2.0", "id": self.id, "method": method, "params": params });
        self.send(&req).await;
        let reply = tokio::time::timeout(Duration::from_secs(10), self.stdout.next_line())
            .await
            .expect("an answer in time")
            .expect("read")
            .expect("a line");
        serde_json::from_str(&reply).expect("json reply")
    }

    /// The MCP handshake an MCP host makes before anything else.
    async fn initialize(&mut self) {
        let init = self
            .request(
                "initialize",
                json!({ "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": { "name": "mcp_lease_e2e", "version": "0" } }),
            )
            .await;
        assert!(init.get("result").is_some(), "{init}");
        self.send(&json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }))
            .await;
    }

    async fn call(&mut self, name: &str, arguments: Value) -> (bool, Value) {
        let reply = self
            .request(
                "tools/call",
                json!({ "name": name, "arguments": arguments }),
            )
            .await;
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

/// Everything the mock panel was sent, in order: `(command, payload)`.
async fn wire(d: &Daemon) -> Vec<(u8, Vec<u8>)> {
    let t = d
        .fleet
        .get(MAC)
        .await
        .expect("known")
        .transport()
        .await
        .expect("linked");
    match &*t {
        DeviceTransport::Mock(m) => m.sent_commands.lock().unwrap().clone(),
        _ => panic!("expected the mock"),
    }
}

/// The 0x8B animation blobs among `sent`, in order.
fn blobs(sent: &[(u8, Vec<u8>)]) -> Vec<Vec<u8>> {
    sent.iter()
        .filter(|(id, _)| *id == 0x8B)
        .map(|(_, b)| b.clone())
        .collect()
}

/// One frame read back off the wire: its duration and its pixels.
struct WireFrame {
    time_ms: u16,
    pixels: Vec<[u8; 3]>,
}

/// Read a 0x8B blob back as the panel would: `AA LLLL TTTT RR NN`, then NN
/// palette colours (0 = 256), then `pixels` indices packed LSB-first at
/// `ceil(log2 NN)` bits each (1 for one colour).
///
/// The pixel count is the panel's, not the blob's: a frame drawn at any other
/// resolution has a different byte count, and that is refused here, so "full
/// resolution" is read off the bytes the panel got, not off a reply that
/// says so.
fn frames_on_the_wire(blob: &[u8], pixels: usize) -> Vec<WireFrame> {
    let mut out = Vec::new();
    let mut at = 0;
    while at < blob.len() {
        let frame = &blob[at..];
        assert!(frame.len() >= 7, "a whole header at {at}");
        assert_eq!(frame[0], 0xAA, "frame {} starts at {at}", out.len());
        let len = usize::from(u16::from_le_bytes([frame[1], frame[2]]));
        let time_ms = u16::from_le_bytes([frame[3], frame[4]]);
        let colours = match frame[6] {
            0 => 256,
            n => usize::from(n),
        };
        let bits = if colours > 1 {
            usize::BITS as usize - (colours - 1).leading_zeros() as usize
        } else {
            1
        };
        let packed = (pixels * bits).div_ceil(8);
        assert_eq!(
            len,
            7 + colours * 3 + packed,
            "frame {} carries exactly {pixels} pixels at {bits} bits",
            out.len()
        );
        let palette: Vec<[u8; 3]> = frame[7..7 + colours * 3]
            .chunks(3)
            .map(|c| [c[0], c[1], c[2]])
            .collect();
        let data = &frame[7 + colours * 3..len];
        let px = (0..pixels)
            .map(|i| {
                let bit = i * bits;
                let word = u32::from(data[bit / 8])
                    | data.get(bit / 8 + 1).map_or(0, |b| u32::from(*b) << 8);
                let index = (word >> (bit % 8)) & ((1 << bits) - 1);
                palette[usize::try_from(index).expect("index")]
            })
            .collect();
        out.push(WireFrame {
            time_ms,
            pixels: px,
        });
        at += len;
    }
    out
}

fn all(frame: &WireFrame, rgb: [u8; 3]) -> bool {
    frame.pixels.iter().all(|p| *p == rgb)
}

/// `get_screen_previews` (API.DV) over the real wire, against the real
/// daemon's record: the animation just drawn is the panel's `frame` state,
/// and its pixels arrive as MCP image content at the index the entry names.
async fn assert_preview_is_an_image(mcp: &mut Mcp) {
    let reply = mcp
        .request(
            "tools/call",
            json!({ "name": "get_screen_previews", "arguments": { "mac": MAC } }),
        )
        .await;
    let result = &reply["result"];
    assert_eq!(result["isError"], json!(false), "{reply}");
    let preview = &result["structuredContent"];
    assert_eq!(preview["daemon"]["state"], json!("running"), "{preview}");
    let entry = &preview["devices"][0];
    assert_eq!(entry["state"], json!("frame"), "{entry}");
    let index = entry["frame"]["image"].as_u64().expect("an image index");
    let block = &result["content"][usize::try_from(index).expect("small")];
    assert_eq!(block["type"], json!("image"), "{block}");
    assert!(block["mimeType"]
        .as_str()
        .is_some_and(|m| m.starts_with("image/")));
    assert!(block["data"].as_str().is_some_and(|d| !d.is_empty()));
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

/// The agent's animation as the panel got it: one 0x8B stream since `before`,
/// two 64x64 frames, red then blue, 100 ms each. Returns where the wire was
/// after it.
async fn assert_drawn_at_full_resolution(d: &Daemon, before: usize) -> usize {
    // The reply is the tool's word; the wire is the panel's. Read the frames
    // back off the bytes the panel got.
    let drawn_at = wire(d).await;
    let theirs = blobs(&drawn_at[before..]);
    assert_eq!(
        theirs.len(),
        1,
        "one 0x8B stream carries the whole animation"
    );
    let frames = frames_on_the_wire(&theirs[0], 64 * 64);
    assert_eq!(frames.len(), 2, "every frame reached the panel");
    assert!(
        all(&frames[0], [255, 0, 0]) && all(&frames[1], [0, 0, 255]),
        "red then blue, every one of the 4096 pixels"
    );
    assert_eq!(
        frames.iter().map(|f| f.time_ms).collect::<Vec<_>>(),
        [100, 100],
        "each frame with its own duration"
    );
    drawn_at.len()
}

/// After the lapse: the widget's own 64x64 frame on the wire past `drawn_at`.
async fn assert_widget_frame_back(d: &Daemon, drawn_at: usize) {
    // "restored: job" is the daemon's word too. The widget's frame must be ON
    // the wire after the agent's animation: a 64x64 frame that is neither of
    // the agent's two.
    let back = blobs(&wire(d).await[drawn_at..]);
    let repaint = back.first().expect("the widget's frame was sent back");
    let repaint = frames_on_the_wire(repaint, 64 * 64);
    assert_eq!(repaint.len(), 1, "one widget frame");
    assert!(
        !all(&repaint[0], [255, 0, 0]) && !all(&repaint[0], [0, 0, 255]),
        "the widget's picture, not the agent's"
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

    mcp.initialize().await;
    assert_mcp_discovery(&mut mcp).await;

    let (bad, lease) = mcp
        .call(
            "lease_acquire",
            json!({ "mac": MAC, "ttl_ms": 1500, "holder": "e2e agent" }),
        )
        .await;
    assert!(!bad, "{lease}");
    let token = lease["lease"].as_str().expect("a lease token").to_string();

    let before = wire(&d).await.len();
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
    let drawn_at = assert_drawn_at_full_resolution(&d, before).await;
    assert_preview_is_an_image(&mut mcp).await;
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
    assert_widget_frame_back(&d, drawn_at).await;
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
