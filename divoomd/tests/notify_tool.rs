//! A notification over MCP shows, then gives the panel back (P4.7).
//!
//! `mcp_tools::call_tool` -- what `divoomd mcp` runs for `tools/call` --
//! against a real daemon on a unix socket, a mock panel running a live
//! widget. The tool returns before the notification ends; while it is up,
//! the GUI is refused and the widget is paused; when the duration runs out
//! the widget's frame is back, with no further call from anyone.

use std::sync::Arc;
use std::time::{Duration, Instant};

use base64::Engine;
use divoomd::daemon::Daemon;
use divoomd::daemon_target::DaemonTarget;
use divoomd::mcp_tools::call_tool;
use divoomd::protocol::make_request;
use divoomd::socket_server::{serve, Handler};
use serde_json::{json, Value};
use tokio::net::UnixListener;

const MAC: &str = "NOTIFY_A";

#[tokio::test(flavor = "multi_thread")]
async fn a_notification_shows_for_its_duration_then_the_widget_returns() {
    let path = std::env::temp_dir().join(format!("divoomd_notify_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let ask = |c: &str, a: Value| d.handle(make_request(c, Some(a), None));
    assert_eq!(
        ask("connect", json!({ "mock": true, "mac": MAC })).await["success"],
        json!(true)
    );
    let job = ask(
        "live_job_start",
        json!({ "mac": MAC, "kind": "sysmon", "params": { "size": 16 } }),
    )
    .await;
    assert_eq!(job["success"], json!(true), "{job}");
    let mut events = d.subscribe().expect("the daemon broadcasts");
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(listener, d.clone(), 8, Duration::from_secs(60)));
    let target = DaemonTarget::Unix(path.to_string_lossy().into_owned());

    let started = Instant::now();
    let shown = call_tool(
        "notify",
        &json!({ "mac": MAC, "text": "Build ok", "duration_ms": 1500, "size": 16 }),
        &target,
    )
    .await
    .expect("shown");
    assert!(
        started.elapsed() < Duration::from_millis(1000),
        "the tool does not wait out the notification"
    );
    assert_eq!(shown["mac"], json!(MAC), "{shown}");

    let rgb = base64::engine::general_purpose::STANDARD.encode(vec![9u8; 16 * 16 * 3]);
    let gui = ask(
        "device_call",
        json!({ "mac": MAC, "method": "show_image",
                "kwargs": { "w": 16, "h": 16, "frames": [{ "rgb_b64": rgb, "time_ms": 100 }] } }),
    )
    .await;
    assert_eq!(
        gui["code"],
        json!("screen_leased"),
        "the notification holds the screen: {gui}"
    );
    assert_eq!(gui["holder"], json!("notification"), "{gui}");
    let kind = d.fleet.get(MAC).await.expect("known").live_kind().await;
    assert_eq!(
        kind.as_deref(),
        Some("sysmon"),
        "the widget is paused, not stopped"
    );

    let deadline = tokio::time::Instant::now() + Duration::from_secs(4);
    let mut ended = None;
    while ended.is_none() && tokio::time::Instant::now() < deadline {
        if let Ok(Ok(ev)) = tokio::time::timeout(Duration::from_millis(100), events.recv()).await {
            if ev["type"] == json!("lease") && ev["state"] == json!("expired") {
                ended = Some(ev);
            }
        }
    }
    let ended = ended.expect("the notification ended by itself");
    assert_eq!(ended["restored"], json!("job"), "{ended}");
    assert!(
        started.elapsed() >= Duration::from_millis(1500),
        "not before its duration"
    );
    let _ = std::fs::remove_file(&path);
}
