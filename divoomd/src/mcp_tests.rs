//! Tests for `crate::mcp`: what a session offers and how a call answers,
//! without a pipe. The wire itself is pinned by `tests/mcp_stdio.rs`.

use super::*;
use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

fn server(allow_destructive: bool) -> DivoomMcp {
    DivoomMcp::new(unreachable(), Options { allow_destructive })
}

fn names(tools: &[Tool]) -> Vec<String> {
    tools.iter().map(|t| t.name.to_string()).collect()
}

#[test]
fn every_catalog_entry_becomes_a_tool() {
    // `tools` drops an entry rmcp cannot read; that must never happen.
    let all = crate::mcp_tools::catalog();
    assert_eq!(
        server(true).tools().len(),
        all.as_array().map_or(0, Vec::len)
    );
    assert_eq!(server(true).tools().len(), 26);
}

#[test]
fn destructive_tools_are_listed_only_when_opted_in() {
    let hidden = [
        "set_alarm",
        "set_low_power",
        "set_radio",
        "set_screen_orientation",
    ];
    let default = names(&server(false).tools());
    let opted = names(&server(true).tools());
    for n in hidden {
        assert!(!default.contains(&n.to_string()), "{n} listed by default");
        assert!(opted.contains(&n.to_string()), "{n} missing when opted in");
    }
    assert_eq!(default.len() + hidden.len(), opted.len());
}

#[test]
fn every_tool_states_its_effect_and_its_reply_shape() {
    for t in server(true).tools() {
        let a = t.annotations.as_ref().expect("annotations");
        assert!(
            a.read_only_hint.is_some() && a.destructive_hint.is_some(),
            "{}",
            t.name
        );
        assert!(
            a.idempotent_hint.is_some() && a.open_world_hint.is_some(),
            "{}",
            t.name
        );
        let out = t.output_schema.as_ref().expect("outputSchema");
        assert_eq!(out.get("type"), Some(&json!("object")), "{}", t.name);
    }
}

#[test]
fn a_tool_that_reaches_a_panel_is_never_read_only() {
    // The read-only set, by name: anything else sends to a panel or changes
    // its state, so a new tool defaults to the safe side of this test.
    let reads = [
        "get_capabilities",
        "get_device_state",
        "list_screens",
        "live_job_list",
        "get_screen_previews",
    ];
    for t in server(true).tools() {
        let ro = t.annotations.as_ref().and_then(|a| a.read_only_hint);
        assert_eq!(ro, Some(reads.contains(&&*t.name)), "{}", t.name);
    }
}

#[tokio::test]
async fn a_destructive_call_is_refused_unless_opted_in_before_any_io() {
    let daemon = FakeDaemon::start(json!({}), None).await;
    let s = DivoomMcp::new(daemon.target.clone(), Options::default());
    let args = json!({ "enabled": true }).as_object().cloned();
    let r = s.call("set_low_power", args).await;
    assert_eq!(r.is_error, Some(true));
    assert_eq!(daemon.requests().len(), 0, "nothing reached the daemon");
}

#[tokio::test]
async fn a_success_is_text_and_the_same_structured_object() {
    let daemon = FakeDaemon::start(json!({}), None).await;
    let s = DivoomMcp::new(daemon.target.clone(), Options::default());
    let r = s
        .call("set_volume", json!({ "level": 7 }).as_object().cloned())
        .await;
    assert_eq!(r.is_error, Some(false));
    let want = json!({ "ok": true, "level": 7 });
    assert_eq!(r.structured_content, Some(want.clone()));
    let text = r.content[0]
        .as_text()
        .map(|t| t.text.clone())
        .unwrap_or_default();
    assert_eq!(serde_json::from_str::<Value>(&text).ok(), Some(want));
}

#[tokio::test]
async fn a_refusal_carries_the_daemons_code() {
    let daemon = FakeDaemon::replying(
        json!({ "success": false, "error": "no panel 'X'", "code": "unknown_device" }),
        None,
    )
    .await;
    let s = DivoomMcp::new(daemon.target.clone(), Options::default());
    let r = s
        .call(
            "set_volume",
            json!({ "level": 7, "mac": "X" }).as_object().cloned(),
        )
        .await;
    assert_eq!(r.is_error, Some(true));
    let text = r.content[0]
        .as_text()
        .map(|t| t.text.clone())
        .unwrap_or_default();
    assert_eq!(
        serde_json::from_str::<Value>(&text).ok(),
        Some(json!({ "error": "no panel 'X'", "code": "unknown_device" }))
    );
}

#[tokio::test]
async fn the_preview_sends_its_frames_as_image_content() {
    let daemon = FakeDaemon::replying(
        json!({ "success": true, "now_ms": 1, "devices": [
            { "id": "A", "state": "frame", "reason": null,
              "frame": { "data_url": "data:image/png;base64,iVBO", "mime": "image/png",
                         "width": 16, "height": 16, "frames": 1 } } ]}),
        None,
    )
    .await;
    let s = DivoomMcp::new(daemon.target.clone(), Options::default());
    let r = s.call(crate::mcp_preview::NAME, None).await;
    assert_eq!(r.is_error, Some(false));
    assert_eq!(r.content.len(), 2, "text, then one image");
    let img = r.content[1].as_image().expect("an image block");
    assert_eq!(
        (img.data.as_str(), img.mime_type.as_str()),
        ("iVBO", "image/png")
    );
    let s = r.structured_content.expect("structured");
    assert_eq!(s["devices"][0]["frame"]["image"], json!(1));
}

#[tokio::test]
async fn an_unknown_tool_is_a_tool_error() {
    let r = server(false).call("no_such_tool", None).await;
    assert_eq!(r.is_error, Some(true));
}

// ── the stdio guard ─────────────────────────────────────────────────────

#[test]
fn a_regular_file_is_not_a_pipe_but_the_pipe_kinds_are() {
    // Both directions. A guard that only ever accepted would also pass.
    use std::ffi::CString;
    use std::os::fd::FromRawFd;

    let dir = std::env::temp_dir().join(format!("divoom-pipe-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("temp dir");

    // A regular file: the `> out.txt` case the guard exists for.
    let file_path = dir.join("out.txt");
    std::fs::write(&file_path, b"x").expect("write file");
    let file = std::fs::File::open(&file_path).expect("open file");
    let fd = std::os::fd::AsRawFd::as_raw_fd(&file);
    assert!(
        !fd_is_pipe_like(fd),
        "a redirected stdout must be rejected, or the server tracebacks on write"
    );

    // A FIFO, opened read-write so opening it cannot block.
    let fifo_path = dir.join("pipe");
    let fifo_c = CString::new(fifo_path.to_str().expect("utf8 path")).expect("cstring");
    // SAFETY: creating a FIFO at a path this test owns, in a directory it
    // created; no memory is shared and `fifo_c` outlives the call.
    assert_eq!(unsafe { libc::mkfifo(fifo_c.as_ptr(), 0o600) }, 0);
    // SAFETY: `O_RDWR` on a FIFO does not block waiting for a peer, and the
    // returned descriptor is owned by the `File` that adopts it below.
    let fifo_fd = unsafe { libc::open(fifo_c.as_ptr(), libc::O_RDWR | libc::O_NONBLOCK) };
    assert!(fifo_fd >= 0, "open the fifo");
    // SAFETY: `fifo_fd` is a fresh descriptor from `open` above; handing it to
    // `File` transfers ownership, so it is closed exactly once, on drop.
    let fifo = unsafe { std::fs::File::from_raw_fd(fifo_fd) };
    assert!(
        fd_is_pipe_like(std::os::fd::AsRawFd::as_raw_fd(&fifo)),
        "a real pipe is exactly what an MCP client provides"
    );

    // A character device: /dev/null, and a terminal is one too.
    let null = std::fs::File::open("/dev/null").expect("open /dev/null");
    assert!(fd_is_pipe_like(std::os::fd::AsRawFd::as_raw_fd(&null)));

    // A socket: what a client on the other side of a socketpair gives us.
    // SAFETY: a socketpair is two descriptors; both are adopted by `File`s.
    let mut pair = [0 as libc::c_int; 2];
    assert_eq!(
        unsafe { libc::socketpair(libc::AF_UNIX, libc::SOCK_STREAM, 0, pair.as_mut_ptr()) },
        0
    );
    // SAFETY: `pair[0]` is a fresh descriptor from the socketpair above;
    // `File` takes ownership and closes it once, on drop.
    let sock = unsafe { std::fs::File::from_raw_fd(pair[0]) };
    assert!(fd_is_pipe_like(std::os::fd::AsRawFd::as_raw_fd(&sock)));

    // A closed descriptor: nothing to read, so not pipe-like. This is the
    // case that would otherwise be a panic or a hang.
    assert!(!fd_is_pipe_like(-1));

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn the_diagnostic_names_the_fix() {
    // Someone reading this in a bare log has to learn what to do next.
    assert!(NOT_A_PIPE.contains("MCP client"));
    assert!(NOT_A_PIPE.contains("docs/MCP_SERVER.md"));
}

/// `docs/MCP_SERVER.md` said 14 tools beside a table of 25 (audit, API.DV):
/// its count and its table are now held to the catalog by this test.
#[test]
fn the_docs_list_exactly_the_catalog_and_count_it() {
    let doc = include_str!("../../docs/MCP_SERVER.md");
    let all = crate::mcp_tools::catalog();
    let mut catalog: Vec<String> = all
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|t| t["name"].as_str().map(str::to_string))
        .collect();
    catalog.sort();
    let table = doc
        .split_once("## Tool Catalog")
        .and_then(|(_, rest)| rest.split_once("### Screen leases"))
        .map_or("", |(t, _)| t);
    let mut documented: Vec<String> = table
        .lines()
        .filter_map(|l| l.strip_prefix("| `"))
        .filter_map(|l| l.split_once('`').map(|(n, _)| n.to_string()))
        .filter(|n| n.chars().all(|c| c.is_ascii_lowercase() || c == '_'))
        .collect();
    documented.sort();
    assert_eq!(documented, catalog, "the Tool Catalog table");
    let default = server(false).tools().len();
    for (i, _) in doc.match_indices(" tools") {
        // "26 tools", and "14 device-control tools" too: a count within the
        // two words before.
        let counted = doc[..i]
            .rsplit(' ')
            .take(2)
            .find_map(|w| w.parse::<usize>().ok());
        if let Some(n) = counted {
            assert!(
                n == catalog.len() || n == default || n == 13,
                "the doc says {n} tools; the catalog has {} ({default} by default)",
                catalog.len()
            );
        }
    }
}
