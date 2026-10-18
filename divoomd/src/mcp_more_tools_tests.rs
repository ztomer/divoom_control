//! The P4.5 tools: what each sends, and that its ranges are the shared ones.

use super::*;
use crate::arg_bounds::{COUNTDOWN_MINUTES, RED_SCORE, VOLUME};
use crate::mcp_daemon::fake::{unreachable, FakeDaemon};
use crate::mcp_tools::call_tool;

fn sent(daemon: &FakeDaemon, method: &str) -> Value {
    daemon
        .requests()
        .into_iter()
        .find(|r| r["args"]["method"] == json!(method) || r["command"] == json!(method))
        .unwrap_or_else(|| panic!("no {method} in {:?}", daemon.requests()))
}

#[test]
fn every_new_tool_is_in_the_one_catalog() {
    let all = crate::mcp_tools::catalog();
    let names: Vec<&str> = all
        .as_array()
        .expect("a list")
        .iter()
        .filter_map(|t| t["name"].as_str())
        .collect();
    for want in [
        "show_text",
        "live_job_start",
        "live_job_stop",
        "live_job_list",
        "set_scoreboard",
        "set_timer",
        "set_countdown",
    ] {
        assert!(names.contains(&want), "{want} missing from {names:?}");
    }
}

#[test]
fn the_schema_ranges_are_the_shared_bounds() {
    let all = crate::mcp_tools::catalog();
    let tool = |n: &str| {
        all.as_array()
            .and_then(|ts| ts.iter().find(|t| t["name"] == json!(n)))
            .cloned()
            .expect("tool")
    };
    assert_eq!(
        tool("set_volume")["inputSchema"]["properties"]["level"],
        VOLUME.schema()
    );
    assert_eq!(
        tool("set_scoreboard")["inputSchema"]["properties"]["red_score"],
        RED_SCORE.schema()
    );
    assert_eq!(
        tool("set_countdown")["inputSchema"]["properties"]["minutes"],
        COUNTDOWN_MINUTES.schema()
    );
}

#[tokio::test]
async fn out_of_range_is_refused_before_any_io() {
    for (name, args) in [
        (
            "set_scoreboard",
            json!({ "red_score": 1000, "blue_score": 0 }),
        ),
        (
            "set_countdown",
            json!({ "action": "start", "minutes": 100 }),
        ),
        ("set_countdown", json!({ "action": "start", "seconds": 60 })),
        ("set_timer", json!({ "action": "lap" })),
        ("live_job_start", json!({ "kind": "screensaver" })),
        ("show_text", json!({ "text": "  " })),
    ] {
        let err = call_tool(name, &args, &unreachable())
            .await
            .expect_err("refused");
        assert!(
            !err.contains("not reachable"),
            "{name} reached for the daemon: {err}"
        );
    }
}

#[tokio::test]
async fn the_built_in_tools_send_what_the_daemon_expects() {
    let daemon = FakeDaemon::start(json!(true), None).await;
    call_tool(
        "set_scoreboard",
        &json!({ "red_score": 12, "blue_score": 7 }),
        &daemon.target,
    )
    .await
    .expect("scoreboard");
    assert_eq!(
        sent(&daemon, "scoreboard.set_scoreboard")["args"]["args"],
        json!([1, 12, 7])
    );

    call_tool("set_timer", &json!({ "action": "reset" }), &daemon.target)
        .await
        .expect("timer");
    assert_eq!(sent(&daemon, "timer.set_timer")["args"]["args"], json!([2]));

    call_tool(
        "set_countdown",
        &json!({ "action": "start", "minutes": 5, "seconds": 30 }),
        &daemon.target,
    )
    .await
    .expect("countdown");
    assert_eq!(
        sent(&daemon, "countdown.set_countdown")["args"]["args"],
        json!([0, 5, 30])
    );
}

#[tokio::test]
async fn a_live_job_goes_to_the_active_panel_at_its_size() {
    let daemon = FakeDaemon::replying(
        json!({ "success": true, "mac": "AA:BB", "width": 64 }),
        None,
    )
    .await;
    let reply = call_tool(
        "live_job_start",
        &json!({ "kind": "sysmon" }),
        &daemon.target,
    )
    .await
    .expect("started");
    assert_eq!(reply["mac"], json!("AA:BB"), "{reply}");
    let start = sent(&daemon, "live_job_start");
    assert_eq!(start["args"]["mac"], json!("AA:BB"));
    assert_eq!(start["args"]["kind"], json!("sysmon"));
    assert_eq!(start["args"]["params"]["size"], json!(64));

    call_tool("live_job_list", &json!({ "mac": "AA:BB" }), &daemon.target)
        .await
        .expect("listed");
    assert_eq!(
        sent(&daemon, "live_job_list")["args"]["mac"],
        json!("AA:BB")
    );
}

#[tokio::test]
async fn text_is_drawn_at_the_panels_size() {
    let frame = base64::engine::general_purpose::STANDARD.encode(vec![255u8; 64 * 64 * 3]);
    let daemon = FakeDaemon::replying(
        json!({ "success": true, "width": 128, "frame_rgb_b64": frame, "result": true }),
        None,
    )
    .await;
    let reply = call_tool("show_text", &json!({ "text": "Hi" }), &daemon.target)
        .await
        .expect("drawn");
    assert_eq!(reply["size"], json!(128), "{reply}");
    let render = sent(&daemon, "render_widget");
    assert_eq!(render["args"]["kind"], json!("text"));
    assert_eq!(
        render["args"]["size"],
        json!(64),
        "the renderer's own ceiling"
    );
    let shown = sent(&daemon, "show_image");
    assert_eq!(shown["args"]["kwargs"]["w"], json!(128));
    let rgb = base64::engine::general_purpose::STANDARD
        .decode(
            shown["args"]["kwargs"]["frames"][0]["rgb_b64"]
                .as_str()
                .expect("frame"),
        )
        .expect("base64");
    assert_eq!(rgb.len(), 128 * 128 * 3);
}
