//! Device failures carry a stable `code` beside the prose (P3.2).
//!
//! `err_reply` carried only `success` and `error`, so a client that wanted to
//! tell "that panel is gone" from "say which panel" had to match wording --
//! making the wording load-bearing, the class `ble_fault.rs` was written to
//! end. Each case drives the real dispatcher (or the real socket server for a
//! line that is not a request) and reads the code.

use std::sync::Arc;
use std::time::Duration;

use divoomd::daemon::Daemon;
use divoomd::protocol::{make_request, ErrorCode};
use divoomd::socket_server::{serve, Handler};
use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::net::{UnixListener, UnixStream};

mod ndjson;
use ndjson::next_line;

async fn ask(d: &Daemon, command: &str, args: Value) -> Value {
    d.handle(make_request(command, Some(args), None)).await
}

fn assert_code(reply: &Value, code: &str) {
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(reply["code"], code, "{reply}");
    assert!(
        reply["error"].is_string(),
        "the prose stays for people: {reply}"
    );
}

#[tokio::test]
async fn a_missing_panel_and_no_panel_are_told_apart_by_code() {
    let d = Daemon::new();
    let named = ask(
        &d,
        "device_call",
        json!({ "method": "get_volume", "mac": "NOPE" }),
    )
    .await;
    assert_code(&named, "device_disconnected");
    let none = ask(&d, "device_call", json!({ "method": "get_volume" })).await;
    assert_code(&none, "no_device");
    let gone = ask(&d, "disconnect", json!({ "mac": "NOPE" })).await;
    assert_code(&gone, "device_disconnected");
}

#[tokio::test]
async fn several_panels_and_no_active_one_says_which_is_needed() {
    let d = Daemon::new();
    for mac in ["A", "B"] {
        let r = ask(&d, "connect", json!({ "mock": true, "mac": mac })).await;
        assert_eq!(r["success"], json!(true), "{r}");
    }
    // The active panel is one that is not linked: a mac-less request has
    // nowhere obvious to go, and the caller must say which.
    let sel = ask(&d, "select_device", json!({ "mac": "Z" })).await;
    assert_eq!(sel["success"], json!(true), "{sel}");
    let r = ask(&d, "device_call", json!({ "method": "get_volume" })).await;
    assert_code(&r, "ambiguous_target");
}

#[tokio::test]
async fn an_unknown_command_and_a_bad_line_have_codes() {
    let d = Daemon::new();
    assert_code(&ask(&d, "frobnicate", json!({})).await, "unknown_command");

    let path = std::env::temp_dir().join(format!("divoomd_codes_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(
        listener,
        Arc::new(Daemon::new()),
        4,
        Duration::from_secs(60),
    ));
    let mut s = UnixStream::connect(&path).await.expect("connect");
    s.write_all(b"not json\n{\"no_command\":1}\n")
        .await
        .expect("write");
    for _ in 0..2 {
        let r = next_line(&mut s, Duration::from_secs(3))
            .await
            .expect("reply");
        assert_code(&r, "bad_request");
    }
    let _ = std::fs::remove_file(&path);
}

#[test]
fn every_code_has_a_distinct_snake_case_wire_name() {
    let names: Vec<&str> = ErrorCode::ALL.iter().map(|c| c.as_str()).collect();
    let mut unique = names.clone();
    unique.sort_unstable();
    unique.dedup();
    assert_eq!(unique.len(), names.len(), "duplicate wire names: {names:?}");
    for n in names {
        assert!(
            n.chars().all(|c| c.is_ascii_lowercase() || c == '_'),
            "{n} is not snake_case"
        );
    }
}

/// A device failure reaches an MCP agent and a CLI script as its class, not
/// only as prose (P5.10): the write fails on a real socket, and the client
/// half (`ToolError::from_reply`, `cli_line`) carries the class.
///
/// The class of a write that could not be sent is `device_disconnected`:
/// the command never left, so the panel is not there any more (P2.8). The
/// receipt this test exists for is that the class REACHES the client -- not
/// which class it is.
#[tokio::test(flavor = "multi_thread")]
async fn a_failed_write_reaches_mcp_and_the_cli_as_its_class() {
    use divoomd::daemon::DeviceTransport;
    use divoomd::daemon_target::DaemonTarget;
    use divoomd::mcp_tools::call_tool;

    let path = std::env::temp_dir().join(format!("divoomd_p510_{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let r = ask(&d, "connect", json!({ "mock": true, "mac": "FAILS" })).await;
    assert_eq!(r["success"], json!(true), "{r}");
    let t = d.current_transport().await.expect("the mock panel");
    let DeviceTransport::Mock(m) = &*t else {
        panic!("expected the mock transport")
    };
    m.set_failing(true);

    let listener = Arc::new(UnixListener::bind(&path).expect("bind"));
    tokio::spawn(serve(listener, d.clone(), 8, Duration::from_secs(60)));
    let target = DaemonTarget::Unix(path.to_string_lossy().into_owned());
    let err = call_tool(
        "set_volume",
        &json!({ "level": 7, "mac": "FAILS" }),
        &target,
    )
    .await
    .expect_err("the write fails");
    assert_eq!(err.code.as_deref(), Some("device_disconnected"), "{err}");
    assert!(
        err.cli_line().ends_with(" [device_disconnected]"),
        "{}",
        err.cli_line()
    );
    let _ = std::fs::remove_file(&path);
}

/// The code table clients read (`docs/MCP_SERVER.md`) lists exactly the
/// codes the daemon can send, so a new code cannot ship undocumented and a
/// retired one cannot linger.
#[test]
fn the_documented_code_table_is_the_code_set() {
    let doc = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../docs/MCP_SERVER.md"),
    )
    .expect("docs/MCP_SERVER.md");
    let start = doc
        .find("<!-- error-codes:start -->")
        .expect("the table's start marker");
    let end = doc
        .find("<!-- error-codes:end -->")
        .expect("the table's end marker");
    let mut documented: Vec<&str> = doc[start..end]
        .lines()
        .filter_map(|l| l.strip_prefix("| `"))
        .filter_map(|l| l.split('`').next())
        .collect();
    let mut codes: Vec<&str> = ErrorCode::ALL.iter().map(|c| c.as_str()).collect();
    documented.sort_unstable();
    codes.sort_unstable();
    assert_eq!(documented, codes, "docs/MCP_SERVER.md vs ErrorCode::ALL");
}
