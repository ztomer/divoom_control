//! The read tools: what a client is told when a panel cannot answer (P2.8).
//!
//! `get_device_state` reads five things. A read that gets no answer used to
//! come back as a null value, which is the same face a value has -- so a
//! client could not tell "the panel has no such value" from "the panel is
//! gone", and the two were the same null. These pin the honest shapes: a
//! value, a null with no daemon at all, and a null WITH the reason the read
//! was refused.

use super::*;
use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

#[tokio::test]
async fn the_read_tools_map_daemon_results_into_their_own_shape() {
    // get_device_state reads THREE things the daemon can read (volume,
    // brightness, light mode); the orientation and the mirror are set by the
    // daemon and never read back, so they are reported as unreadable rather
    // than asked for and reported as a panel that did not answer. A read
    // tool that silently returns nulls is how a client shows a device as
    // blank when it is merely unreachable.
    let daemon = FakeDaemon::start(json!({ "value": 42 }), None).await;
    let state = call_tool("get_device_state", &json!({}), &daemon.target)
        .await
        .expect("state");
    for key in ["volume", "brightness", "light_mode"] {
        assert_eq!(
            state[key],
            json!({ "value": 42 }),
            "{key} lost its result: {state}"
        );
    }
    for key in ["screen_orientation", "mirror"] {
        assert_eq!(state[key], json!(null), "{key} has no read: {state}");
        assert_eq!(
            state["errors"][key]["code"],
            json!("unsupported"),
            "{key} must say it cannot be read: {state}"
        );
    }
    assert_eq!(daemon.requests().len(), 3, "three real reads");
}

#[tokio::test]
async fn an_unreachable_daemon_yields_nulls_rather_than_a_false_reading() {
    // The distinction that matters: absent data must be visibly absent, not
    // zero. Zero is a real volume.
    let state = call_tool("get_device_state", &json!({}), &unreachable())
        .await
        .expect("a read against no daemon still returns its shape");
    for key in [
        "volume",
        "brightness",
        "light_mode",
        "screen_orientation",
        "mirror",
    ] {
        assert_eq!(state[key], json!(null), "{key} must be null, not a default");
    }
    // No daemon is not a refused read: the only reasons named are the two
    // fields this daemon cannot read at all.
    let named: Vec<&str> = state["errors"]
        .as_object()
        .expect("the errors map")
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(
        named,
        vec!["mirror", "screen_orientation"],
        "only the unreadable fields are named: {state}"
    );
}

/// A read the daemon REFUSED is not an absent value: the field is null (so
/// nothing shows a value that was never read) and the reason is named, with
/// the daemon's code (P2.8).
#[tokio::test]
async fn a_refused_read_is_named_rather_than_shown_as_no_value() {
    let daemon = FakeDaemon::replying(
        json!({
            "success": false,
            "error": "music.get_volume: the panel did not answer 0x09",
            "code": "device_failed",
        }),
        None,
    )
    .await;
    let state = call_tool("get_device_state", &json!({}), &daemon.target)
        .await
        .expect("the tool still returns its shape");
    assert_eq!(state["volume"], json!(null), "{state}");
    assert_eq!(
        state["errors"]["volume"]["code"],
        json!("device_failed"),
        "the refusal is named with its code: {state}"
    );
    assert!(
        state["errors"]["volume"]["error"]
            .as_str()
            .is_some_and(|e| e.contains("did not answer")),
        "the refusal is named with its reason: {state}"
    );
}

/// The light-mode read is `light.get_light_mode`: the tool used to ask for
/// `control.get_light_mode`, which is not a method the daemon routes, so the
/// field reported "no value" for a read that never ran (P2.8).
#[tokio::test]
async fn the_device_state_reads_the_methods_the_daemon_routes() {
    let daemon = FakeDaemon::start(json!({ "value": 1 }), None).await;
    let state = call_tool("get_device_state", &json!({}), &daemon.target)
        .await
        .expect("state");
    let methods: Vec<String> = daemon
        .requests()
        .iter()
        .map(|r| r["args"]["method"].as_str().unwrap_or_default().to_string())
        .collect();
    assert!(
        methods.contains(&"light.get_light_mode".to_string()),
        "the routed name: {methods:?}"
    );
    for m in &methods {
        assert!(
            crate::device_call::routing::all_methods().any(|r| r == m),
            "{m} is not a method the daemon routes: {methods:?}"
        );
    }
    // The orientation and the mirror are set by the daemon and never read
    // back: the tool says so rather than asking for a method that does not
    // exist and reporting the refusal as a panel that did not answer.
    assert_eq!(methods.len(), 3, "only the three real reads: {methods:?}");
    assert_eq!(
        state["errors"]["screen_orientation"]["code"],
        json!("unsupported"),
        "{state}"
    );
}
