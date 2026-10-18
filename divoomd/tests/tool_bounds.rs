//! The daemon's tool handlers refuse what the shared bounds refuse (P4.5).
//!
//! `countdown.set_countdown` narrowed minutes and seconds to a byte, so 300
//! minutes reached the panel as 44; `set_scoreboard` clamped 1500 to 999 and
//! said nothing. Both now check `divoomd::arg_bounds` -- the same statements
//! the MCP schema is generated from -- and say what was wrong.

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::{json, Value};

async fn call(d: &Daemon, method: &str, args: Value) -> Value {
    d.handle(make_request(
        "device_call",
        Some(json!({ "mac": "M", "method": method, "args": args })),
        None,
    ))
    .await
}

#[tokio::test]
async fn out_of_range_tool_values_are_refused_not_narrowed() {
    let d = Daemon::new();
    let r = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": "M" })),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");

    for (method, args, key) in [
        ("countdown.set_countdown", json!([0, 300, 0]), "minutes"),
        ("countdown.set_countdown", json!([0, 5, 75]), "seconds"),
        (
            "scoreboard.set_scoreboard",
            json!([1, 1500, 0]),
            "red_score",
        ),
        ("scoreboard.set_scoreboard", json!([1, 0, -3]), "blue_score"),
    ] {
        let r = call(&d, method, args).await;
        assert_eq!(r["success"], json!(false), "{method}: {r}");
        assert!(
            r["error"].as_str().is_some_and(|e| e.contains(key)),
            "{method}: the refusal names {key}: {r}"
        );
    }
    // In range still works.
    let ok = call(&d, "countdown.set_countdown", json!([0, 99, 59])).await;
    assert_eq!(ok["success"], json!(true), "{ok}");
    let ok = call(&d, "scoreboard.set_scoreboard", json!([1, 999, 0])).await;
    assert_eq!(ok["success"], json!(true), "{ok}");
}
