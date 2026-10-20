//! P2.8: a dropped link does not read as connected, and a read that gets no
//! answer does not read as a successful null.
//!
//! The report (2026-10-18): after a `0x74` write the Pixoo-1 stopped
//! answering. Every later call failed `Peripheral no longer available`, yet
//! `device_status` kept saying `connected: true` and `light.get_light_mode`
//! answered `{"success": true, "result": null}` -- a failed read dressed as a
//! success. No disconnect line was logged.
//!
//! Two failures, one class: a failure laundered into a success shape. The
//! daemon's own vocabulary for a link that is gone already exists -- the two
//! broadcasts `mock_simulate_drop` walks (degraded, then disconnected, then
//! the owned-device list) -- so a REAL drop must walk the same road, and a
//! read that got nothing must fail with a code instead of answering null.
//!
//! The mock panel is the seam: `MockTransport::set_failing(true)` is a link
//! that went away mid-call (every write fails), and a mock with no staged
//! reply is a panel that did not answer.

use crate::daemon::{Daemon, DeviceTransport};
use crate::mock_transport::MockTransport;
use crate::protocol::make_request;
use crate::socket_server::Handler;
use serde_json::{json, Value};

const PANEL: &str = "P28_PANEL";

/// Every read the daemon answers, by the name a client calls it with.
///
/// The class, not the instance: one read failing is a bug, one read among
/// twenty-eight failing the same way is a class. The list is the sweep's
/// subject -- a read added later must be added here, or the sweep does not
/// know about it.
const READ_METHODS: &[&str] = &[
    "get_device_name",
    "get_brightness",
    "get_light_mode",
    "get_volume",
    "get_low_power_switch",
    "get_auto_power_off",
    "get_alarm_time",
    "get_memorial_time",
    "get_play_status",
    "get_sd_music_list_total_num",
    "get_sd_music_info",
    "get_sd_play_name",
    "modify_user_gif_items",
    "app_get_user_define_info",
    "get_sleep_scene",
    "get_user_define_time",
    "get_scoreboard",
    "get_timer",
    "get_countdown",
    "get_noise",
    "get_tool_info",
    "get_sound_control",
    "get_work_mode",
    "get_device_temp",
    "get_net_temp_disp",
];

/// A daemon with ONE mock panel linked, and no name cached (so a read of the
/// name really goes to the panel instead of answering from the cache).
async fn daemon_with_panel() -> Daemon {
    let d = Daemon::new();
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": PANEL, "name": "" })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    d
}

async fn mock_of(d: &Daemon) -> MockTransport {
    let dev = d.fleet.get(PANEL).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    match &*transport {
        DeviceTransport::Mock(m) => m.clone(),
        _ => panic!("expected the mock transport"),
    }
}

async fn call(d: &Daemon, method: &str) -> Value {
    d.handle(make_request(
        "device_call",
        Some(json!({ "method": method, "args": [], "mac": PANEL })),
        None,
    ))
    .await
}

/// A read that got no answer is a FAILURE with a code -- not a success whose
/// result is null (P2.8).
#[tokio::test]
async fn a_read_that_gets_no_answer_fails_instead_of_answering_null() {
    let d = daemon_with_panel().await;
    let reply = call(&d, "get_brightness").await;
    assert_eq!(
        reply["success"],
        json!(false),
        "a read that got no answer is a failure: {reply}"
    );
    assert!(
        reply.get("code").and_then(Value::as_str).is_some(),
        "the failure carries a code a client can branch on: {reply}"
    );
    assert!(
        reply.get("error").and_then(Value::as_str).is_some(),
        "the failure carries prose: {reply}"
    );
}

/// The CLASS: every read the daemon answers fails the same way when the panel
/// answers nothing. One read is a bug; twenty-four reads that all launder
/// the same failure into a null are a class, and the class is what this pins.
#[tokio::test]
async fn every_read_that_gets_no_answer_fails_rather_than_answering_null() {
    for method in READ_METHODS {
        let d = daemon_with_panel().await;
        let reply = call(&d, method).await;
        assert_ne!(
            reply["success"],
            json!(true),
            "{method} answered success for a read that got nothing: {reply}"
        );
        assert!(
            reply.get("code").and_then(Value::as_str).is_some(),
            "{method} failed with no code: {reply}"
        );
    }
}

/// A link that went away mid-call is not a connected panel: `device_status`
/// says so, for the panel named and for the fleet.
#[tokio::test]
async fn a_dropped_link_does_not_read_as_connected() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    // The panel's link goes away between the connect and the call.
    mock.set_failing(true);

    let reply = call(&d, "get_brightness").await;
    assert_eq!(
        reply["success"],
        json!(false),
        "a call on a dropped link fails: {reply}"
    );

    let named = d
        .handle(make_request(
            "device_status",
            Some(json!({ "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(
        named["connected"],
        json!(false),
        "the dropped panel still reads as connected: {named}"
    );

    let fleet = d.handle(make_request("device_status", None, None)).await;
    assert_eq!(
        fleet["connected"],
        json!(false),
        "the fleet still reads as connected: {fleet}"
    );
}

/// The drop is REPORTED: the same status broadcast a simulated drop sends, so
/// the UI learns of it without polling.
#[tokio::test]
async fn a_dropped_link_is_reported_on_the_event_bus() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    let mut rx = d.tx.subscribe();
    mock.set_failing(true);

    let reply = call(&d, "get_brightness").await;
    assert_eq!(reply["success"], json!(false), "{reply}");

    let mut disconnected = None;
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("status") && ev["connected"] == json!(false) {
            disconnected = Some(ev.clone());
        }
    }
    let ev = disconnected.expect("no disconnected status event was published");
    assert_eq!(ev["state"], json!("disconnected"), "{ev}");
    assert_eq!(ev["mac"], json!(PANEL), "{ev}");
}

/// A panel that is quiet is not a panel that is gone: a read that timed out
/// fails, but the link stays, so the next call can still succeed.
#[tokio::test]
async fn a_panel_that_did_not_answer_keeps_its_link() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    // The panel answers, but not this command.
    mock.simulated_responses
        .lock()
        .expect("the mock's replies")
        .insert(0x09, vec![7]);

    let quiet = call(&d, "get_brightness").await;
    assert_eq!(quiet["success"], json!(false), "{quiet}");
    assert_ne!(
        quiet["code"],
        json!("device_disconnected"),
        "a panel that did not answer is not a dropped link: {quiet}"
    );

    // The link is still there: the read that CAN be answered still works.
    let answered = call(&d, "get_volume").await;
    assert_eq!(answered["success"], json!(true), "{answered}");
    assert_eq!(answered["result"], json!(7), "{answered}");
}
