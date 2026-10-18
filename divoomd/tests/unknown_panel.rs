//! The daemon refuses a panel action for a panel it has never linked (P5.8).
//!
//! `live_job_start` and `set_device_activity` used to call
//! `fleet.get_or_create(mac)`, so any mac a client named became a fleet entry:
//! a job on that phantom panel painted nothing and reported success, and an
//! activity record put a tile for it in the menubar. A fleet entry is now made
//! only by a link (`Fleet::adopt`); a request naming anything else is refused
//! with `unknown_device`, naming the mac. A panel that WAS linked and dropped
//! is still known, so a job started on it waits for the link.
//!
//! `MatrixWall` is the GUI's name for the wall surface, not a panel: the
//! daemon draws the wall through `wall_configure`'s slots, and a live job
//! runs on ONE panel's link. It is refused like any other unknown id, even
//! with a wall configured over linked panels.

use std::sync::Arc;
use std::time::Duration;

use divoomd::daemon::Daemon;
use divoomd::daemon_target::DaemonTarget;
use divoomd::mcp_tools::call_tool;
use divoomd::protocol::make_request;
use divoomd::socket_server::{serve, Handler};
use serde_json::{json, Value};
use tokio::net::UnixListener;

const LINKED: &str = "P58_LINKED";
const PHANTOM: &str = "P58_NEVER_LINKED";

async fn daemon_with(macs: &[&str]) -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    for mac in macs {
        let r = ask(&d, "connect", json!({ "mock": true, "mac": mac })).await;
        assert_eq!(r["success"], json!(true), "{r}");
    }
    d
}

async fn ask(d: &Daemon, command: &str, args: Value) -> Value {
    d.handle(make_request(command, Some(args), None)).await
}

fn start(mac: &str) -> Value {
    json!({ "mac": mac, "kind": "sysmon", "params": { "size": 16 } })
}

fn activity(mac: &str) -> Value {
    json!({ "mac": mac, "kind": "custom_art", "name": "Ditoo" })
}

/// A refusal that a program can branch on and a person can act on.
fn assert_unknown(reply: &Value, mac: &str) {
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(reply["code"], json!("unknown_device"), "{reply}");
    let prose = reply["error"].as_str().unwrap_or_default();
    assert!(prose.contains(mac), "the error names the mac: {reply}");
}

/// Nothing about `mac` is left behind anywhere a client can see.
async fn assert_no_trace(d: &Daemon, mac: &str) {
    assert!(
        d.fleet.get(mac).await.is_none(),
        "{mac} became a fleet entry"
    );
    let jobs = ask(d, "live_job_list", json!({})).await;
    assert_eq!(jobs["jobs"], json!([]), "{jobs}");
    let act = ask(d, "get_device_activity", json!({})).await;
    assert!(act["activity"].get(mac).is_none(), "{act}");
    let owned = ask(d, "owned_devices", json!({})).await;
    assert!(
        !owned.to_string().contains(mac),
        "{mac} listed as owned: {owned}"
    );
}

#[tokio::test]
async fn a_live_job_or_activity_on_a_never_linked_panel_is_refused_by_code() {
    let d = daemon_with(&[LINKED]).await;
    let mut events = d.subscribe().expect("the daemon broadcasts");
    assert_unknown(&ask(&d, "live_job_start", start(PHANTOM)).await, PHANTOM);
    assert_unknown(
        &ask(&d, "set_device_activity", activity(PHANTOM)).await,
        PHANTOM,
    );
    assert_no_trace(&d, PHANTOM).await;
    while let Ok(ev) = events.try_recv() {
        assert_ne!(
            ev["type"],
            json!("activity"),
            "a refused record was broadcast: {ev}"
        );
    }
}

#[tokio::test]
async fn the_wall_is_not_a_panel_even_with_a_wall_configured() {
    let d = daemon_with(&["P58_A", "P58_B"]).await;
    let wall = ask(
        &d,
        "wall_configure",
        json!({ "slots": {
            "P58_A": { "x": 0, "y": 0, "size": 16 },
            "P58_B": { "x": 1, "y": 0, "size": 16 },
        } }),
    )
    .await;
    assert_eq!(wall["wall"], json!(true), "{wall}");
    for wall_id in ["MatrixWall", "matrixwall"] {
        assert_unknown(&ask(&d, "live_job_start", start(wall_id)).await, wall_id);
        assert_unknown(
            &ask(&d, "set_device_activity", activity(wall_id)).await,
            wall_id,
        );
        assert_no_trace(&d, wall_id).await;
    }
}

#[tokio::test]
async fn a_forgotten_panel_is_unknown_again() {
    // `disconnect` forgets a panel (its job stopped, its identity gone); a
    // dropped LINK does not. After a forget the daemon has no link to wait
    // for, so a job there would be the phantom again.
    let d = daemon_with(&[LINKED]).await;
    let gone = ask(&d, "disconnect", json!({ "mac": LINKED })).await;
    assert_eq!(gone["success"], json!(true), "{gone}");
    assert_unknown(&ask(&d, "live_job_start", start(LINKED)).await, LINKED);
    assert_no_trace(&d, LINKED).await;
}

#[tokio::test]
async fn a_dropped_panel_keeps_a_new_job_waiting_for_its_link() {
    let d = daemon_with(&[LINKED]).await;
    let dropped = ask(&d, "mock_simulate_drop", json!({ "mac": LINKED })).await;
    assert_eq!(dropped["success"], json!(true), "{dropped}");
    let dev = d
        .fleet
        .get(LINKED)
        .await
        .expect("identity kept over a drop");
    assert!(!dev.is_connected().await);

    let job = ask(&d, "live_job_start", start(LINKED)).await;
    assert_eq!(job["success"], json!(true), "{job}");
    let act = ask(&d, "set_device_activity", activity(LINKED)).await;
    assert_eq!(act["success"], json!(true), "{act}");

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    let state = loop {
        let jobs = ask(&d, "live_job_list", json!({ "mac": LINKED })).await;
        let state = jobs["jobs"][0]["state"].clone();
        if state == json!("waiting_for_device") || tokio::time::Instant::now() >= deadline {
            break state;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    };
    assert_eq!(state, json!("waiting_for_device"));
    ask(
        &d,
        "live_job_stop",
        json!({ "mac": LINKED, "kind": "sysmon" }),
    )
    .await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_mcp_client_gets_the_code_beside_the_prose() {
    let path = std::env::temp_dir().join(format!("divoomd_p58_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let d = daemon_with(&[LINKED]).await;
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(listener, d.clone(), 8, Duration::from_secs(60)));
    let target = DaemonTarget::Unix(path.to_string_lossy().into_owned());

    let err = call_tool(
        "live_job_start",
        &json!({ "mac": PHANTOM, "kind": "sysmon" }),
        &target,
    )
    .await
    .expect_err("a phantom panel is refused");
    assert_eq!(err.code.as_deref(), Some("unknown_device"), "{err}");
    assert!(err.message.contains(PHANTOM), "{err}");
    assert_no_trace(&d, PHANTOM).await;
    let _ = std::fs::remove_file(&path);
}
