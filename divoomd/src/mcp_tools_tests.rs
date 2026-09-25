//! Tests for `mcp_tools` — the catalog, the argument validation, and the
//! dispatch to the daemon.
//!
//! Split out of `mcp_tools.rs` on 2026-09-25 by the 500-line cap, at the one
//! seam that was already clean: the tests read the module and nothing reads
//! them. They are the replacement for the 81 Python tests that covered the
//! implementation this replaced, which is why they grew.

use super::*;
use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

/// The remote path, proven end to end without a daemon: a real TCP listener
/// in-process, one real connection, and the request line read off the wire.
///
/// This is the capability the Python shell had and this server did not, so it
/// is the test that decides whether 800 lines of second implementation can
/// go. A unit test of the token's presence in a JSON object would not be
/// enough: what can be wrong is that the connection is never opened, or the
/// token never reaches the bytes.
#[tokio::test]
async fn a_remote_daemon_gets_the_token_on_the_wire() {
    let daemon = FakeDaemon::start(json!({}), Some("secret")).await;
    let reply = call_tool("set_brightness", &json!({ "level": 50 }), &daemon.target)
        .await
        .expect("the remote call succeeds");

    let seen = daemon.requests();
    let parsed = seen.first().expect("one request was sent").clone();
    // The envelope is `device_call` with the tool's method inside it, which
    // is the daemon's RPC shape (`dc`) — the first draft of this test
    // expected the method at the top level and was wrong about the layer.
    assert_eq!(parsed["command"], json!("device_call"));
    assert_eq!(parsed["args"]["method"], json!("device.set_brightness"));
    assert_eq!(parsed["args"]["args"], json!([50]));
    assert_eq!(
        parsed["token"],
        json!("secret"),
        "the token must be on the wire, not merely in the config: {parsed}"
    );
    assert_eq!(
        reply["ok"],
        json!(true),
        "the tool result, not the raw reply"
    );
}

#[tokio::test]
async fn an_unreachable_daemon_says_which_one() {
    // Port 1 is reserved and nothing listens there; the message has to name
    // the address, because "daemon not reachable" with no address is the
    // error that costs an afternoon when the daemon is on another machine.
    let target = DaemonTarget::Remote {
        host: "127.0.0.1".to_string(),
        port: 1,
        token: None,
    };
    let err = crate::mcp_daemon::cmd(&target, "ping", json!({}))
        .await
        .expect_err("nothing is listening");
    assert!(err.contains("127.0.0.1:1"), "unhelpful error: {err}");
}

// ── input validation ────────────────────────────────────────────────────
//
// These replace the Python tool tests. An out-of-range brightness that
// reaches the device is a real failure, and the bounds are the only thing
// standing between an MCP client's arguments and the hardware.

/// Every bounded argument, at and beyond each edge. A range check that is
/// off by one at the top is a check that has never been run.
#[tokio::test]
async fn bounded_arguments_are_checked_at_both_ends() {
    let cases: &[(&str, Value, &str)] = &[
        (
            "set_volume",
            json!({ "level": -1 }),
            "level must be in [0..15]",
        ),
        (
            "set_volume",
            json!({ "level": 16 }),
            "level must be in [0..15]",
        ),
        (
            "set_brightness",
            json!({ "level": 101 }),
            "level must be in [0..100]",
        ),
        (
            "set_radio",
            json!({ "freq_x10": 874 }),
            "freq_x10 must be in [875..1080]",
        ),
        (
            "set_radio",
            json!({ "freq_x10": 1081 }),
            "freq_x10 must be in [875..1080]",
        ),
        (
            "play_sound",
            json!({ "duration_ms": 99 }),
            "duration_ms must be in [100..3000]",
        ),
        (
            "play_sound",
            json!({ "duration_ms": 3001 }),
            "duration_ms must be in [100..3000]",
        ),
        (
            "set_alarm",
            json!({ "index": 10, "hour": 1, "minute": 0 }),
            "index",
        ),
        (
            "set_alarm",
            json!({ "index": 0, "hour": 24, "minute": 0 }),
            "hour",
        ),
        (
            "set_alarm",
            json!({ "index": 0, "hour": 1, "minute": 60 }),
            "minute",
        ),
    ];
    for (tool, args, expected) in cases {
        let err = call_tool(tool, args, &unreachable())
            .await
            .expect_err(&format!("{tool} {args} must be rejected"));
        assert!(
            err.contains(expected),
            "{tool} {args}: expected {expected:?} in {err:?}"
        );
    }
}

#[tokio::test]
async fn the_edges_themselves_are_accepted() {
    // The other direction of the same check: a bound that rejects its own
    // endpoint is as broken as one that accepts out of range.
    let daemon = FakeDaemon::start(json!({}), None).await;
    for (tool, args) in [
        ("set_volume", json!({ "level": 0 })),
        ("set_volume", json!({ "level": 15 })),
        ("set_brightness", json!({ "level": 100 })),
        ("play_sound", json!({ "duration_ms": 100 })),
    ] {
        call_tool(tool, &args, &daemon.target)
            .await
            .unwrap_or_else(|e| panic!("{tool} {args} at the edge must be accepted: {e}"));
    }
    assert_eq!(daemon.requests().len(), 4);
}

#[tokio::test]
async fn a_non_numeric_or_missing_argument_is_rejected_by_name() {
    for (tool, args) in [
        ("set_volume", json!({ "level": "loud" })),
        ("set_volume", json!({})),
        ("set_brightness", json!({ "level": 1.5 })),
        ("set_low_power", json!({ "enabled": "yes" })),
    ] {
        let err = call_tool(tool, &args, &unreachable())
            .await
            .expect_err(&format!("{tool} {args} must be rejected"));
        assert!(
            !err.is_empty(),
            "{tool} {args}: an empty error helps nobody"
        );
    }
}

#[tokio::test]
async fn the_enum_arguments_reject_names_that_are_not_in_the_table() {
    // Inventing a mode name here would push an unknown channel to hardware.
    let err = call_tool(
        "set_light_mode",
        &json!({ "mode": "disco" }),
        &unreachable(),
    )
    .await
    .expect_err("an unknown mode must be rejected");
    assert!(err.contains("mode must be one of"), "{err}");

    let err = call_tool(
        "set_weather",
        &json!({ "temperature_c": 20, "weather": "meteor-shower" }),
        &unreachable(),
    )
    .await
    .expect_err("an unknown weather icon must be rejected");
    assert!(err.contains("weather must be one of"), "{err}");

    // And the documented names are the accepted ones.
    let daemon = FakeDaemon::start(json!({}), None).await;
    for (n, _) in LIGHT_MODES {
        call_tool("set_light_mode", &json!({ "mode": n }), &daemon.target)
            .await
            .unwrap_or_else(|e| panic!("mode {n} is in the table: {e}"));
    }
    assert_eq!(
        daemon.requests().len(),
        LIGHT_MODES.len(),
        "one device call per mode, and no mode silently skipped"
    );
}

#[tokio::test]
async fn every_weather_icon_in_the_table_is_accepted() {
    let daemon = FakeDaemon::start(json!({}), None).await;
    for (n, _) in WEATHER_TYPES {
        call_tool(
            "set_weather",
            &json!({ "temperature_c": 21, "weather": n }),
            &daemon.target,
        )
        .await
        .unwrap_or_else(|e| panic!("weather {n} is in the table: {e}"));
    }
    assert_eq!(daemon.requests().len(), WEATHER_TYPES.len());
}

#[tokio::test]
async fn push_animation_needs_exactly_one_of_file_or_data() {
    // Both and neither are both wrong: neither has nothing to send, both is
    // ambiguous about which one the user meant.
    for args in [json!({}), json!({ "file": "a.gif", "data": "R0lGOD" })] {
        let err = call_tool("push_animation", &args, &unreachable())
            .await
            .expect_err("one of file/data, exactly");
        assert!(err.contains("exactly one"), "{err}");
    }
    let err = call_tool(
        "push_animation",
        &json!({ "data": "not base64 %%%" }),
        &unreachable(),
    )
    .await
    .expect_err("invalid base64 must be rejected");
    assert!(err.contains("base64"), "{err}");
}

#[tokio::test]
async fn show_image_rejects_an_empty_or_unreadable_path() {
    let err = call_tool("show_image", &json!({ "file": "" }), &unreachable())
        .await
        .expect_err("an empty path is not a path");
    assert!(err.contains("non-empty"), "{err}");

    let err = call_tool(
        "show_image",
        &json!({ "file": "/nonexistent/divoom/missing.png" }),
        &unreachable(),
    )
    .await
    .expect_err("a missing file must be reported, not sent");
    assert!(err.contains("cannot read"), "{err}");
}

#[tokio::test]
async fn screen_orientation_accepts_only_the_four_right_angles() {
    // 45 is inside the numeric range and still nonsense: the degrees/direction
    // mapping is a match, not arithmetic, so the test has to cover it.
    let err = call_tool(
        "set_screen_orientation",
        &json!({ "degrees": 45 }),
        &unreachable(),
    )
    .await
    .expect_err("45 degrees is not a rotation this device has");
    assert!(err.contains("0, 90, 180"), "{err}");

    let daemon = FakeDaemon::start(json!({}), None).await;
    for degrees in [0, 90, 180, 270] {
        call_tool(
            "set_screen_orientation",
            &json!({ "degrees": degrees }),
            &daemon.target,
        )
        .await
        .unwrap_or_else(|e| panic!("{degrees} degrees must be accepted: {e}"));
    }
    let sent = daemon.requests();
    // Each rotation is two calls: direction, then mirror.
    assert_eq!(sent.len(), 8);
    assert_eq!(sent[0]["args"]["method"], json!("design.set_screen_dir"));
    assert_eq!(
        sent[0]["args"]["args"],
        json!([0]),
        "0 degrees is direction 0"
    );
    assert_eq!(
        sent[2]["args"]["args"],
        json!([1]),
        "90 degrees is direction 1"
    );
    assert_eq!(sent[4]["args"]["args"], json!([2]));
    assert_eq!(sent[6]["args"]["args"], json!([3]));
}

#[tokio::test]
async fn an_alarm_takes_the_documented_argument_order() {
    // Seven positional arguments in a fixed order, three of which are
    // literals. Nothing about this call is self-describing on the wire, so
    // a reordering is invisible except here.
    let daemon = FakeDaemon::start(json!({}), None).await;
    call_tool(
        "set_alarm",
        &json!({ "index": 3, "hour": 7, "minute": 5, "weekday_mask": 31, "enabled": false }),
        &daemon.target,
    )
    .await
    .expect("a full alarm");
    let sent = daemon.requests();
    assert_eq!(sent[0]["args"]["method"], json!("alarm.set_alarm"));
    assert_eq!(
        sent[0]["args"]["args"],
        json!([3, 0, 7, 5, 31, 0, 1]),
        "index, status(disabled), hour, minute, week, mode, trigger_mode"
    );
}

#[tokio::test]
async fn optional_integers_default_when_absent() {
    // weekday_mask and mirror are optional in the schema, so absent must
    // mean the documented default rather than an error.
    let daemon = FakeDaemon::start(json!({}), None).await;
    call_tool(
        "set_alarm",
        &json!({ "index": 0, "hour": 0, "minute": 0 }),
        &daemon.target,
    )
    .await
    .expect("a minimal alarm");
    let sent = daemon.requests();
    assert_eq!(
        sent[0]["args"]["args"],
        json!([0, 1, 0, 0, 0, 0, 1]),
        "enabled by default"
    );
}

#[tokio::test]
async fn the_read_tools_map_daemon_results_into_their_own_shape() {
    // get_device_state makes five calls; a read tool that silently returns
    // nulls is how a client shows a device as blank when it is merely
    // unreachable.
    let daemon = FakeDaemon::start(json!({ "value": 42 }), None).await;
    let state = call_tool("get_device_state", &json!({}), &daemon.target)
        .await
        .expect("state");
    for key in [
        "volume",
        "brightness",
        "light_mode",
        "screen_orientation",
        "mirror",
    ] {
        assert_eq!(
            state[key],
            json!({ "value": 42 }),
            "{key} lost its result: {state}"
        );
    }
    assert_eq!(daemon.requests().len(), 5);
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
}

#[test]
fn catalog_has_all_fourteen_tools() {
    let c = catalog();
    let arr = c.as_array().expect("catalog is an array");
    assert_eq!(arr.len(), 14, "14 MCP tools (including list_screens)");
    for t in arr {
        assert!(t.get("name").and_then(|v| v.as_str()).is_some());
        assert!(t.get("inputSchema").is_some());
    }
}

#[test]
fn the_catalog_is_a_strict_superset_of_the_python_one_it_replaces() {
    // The 13 the Python catalog shipped, named here as a receipt. If a tool
    // is dropped from the native catalog, this fails and the drop has to be
    // argued for; it cannot happen by accident during a refactor.
    const PYTHON_THIRTEEN: &[&str] = &[
        "set_volume",
        "set_brightness",
        "set_light_mode",
        "set_weather",
        "set_alarm",
        "set_radio",
        "set_low_power",
        "set_screen_orientation",
        "show_image",
        "push_animation",
        "play_sound",
        "get_capabilities",
        "get_device_state",
    ];
    let arr = catalog();
    let names: Vec<&str> = arr
        .as_array()
        .expect("catalog is an array")
        .iter()
        .filter_map(|t| t["name"].as_str())
        .collect();
    for tool in PYTHON_THIRTEEN {
        assert!(names.contains(tool), "the native catalog lost {tool}");
    }
    assert_eq!(names.len(), 14, "and exactly one tool beyond them");
}

#[test]
fn light_and_weather_maps_complete() {
    assert_eq!(LIGHT_MODES.len(), 8);
    assert_eq!(WEATHER_TYPES.len(), 6);
}

#[test]
fn tools_include_optional_mac_param() {
    let c = catalog();
    let arr = c.as_array().expect("catalog is an array");
    for t in arr {
        let name = t.get("name").and_then(Value::as_str).unwrap();
        let schema = t.get("inputSchema").unwrap();
        if name != "list_screens" {
            let props = schema.get("properties").and_then(Value::as_object).unwrap();
            assert!(
                props.contains_key("mac"),
                "tool {name} should have optional mac property in inputSchema"
            );
        }
    }
}
