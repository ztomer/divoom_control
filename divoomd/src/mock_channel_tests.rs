//! A channel write lands on the panel its `device_call` names, not on the
//! daemon's selected panel (P5.6).
//!
//! The GUI used to send channel writes (`switch_channel`, `show_clock` and the
//! rest) with no mac, so they reached whichever panel was selected when the
//! write arrived -- after a selection change, the wrong one. It names the panel
//! on every call now; these pin that the daemon honours the name over its own
//! selection, with two mock panels and the OTHER one selected.

use crate::daemon::{Daemon, DeviceTransport};
use crate::mock_transport::MockTransport;
use crate::protocol::make_request;
use crate::socket_server::Handler;
use serde_json::{json, Value};

const A: &str = "AA:00:00:00:00:01";
const B: &str = "BB:00:00:00:00:02";

async fn two_panels_with_b_selected() -> Daemon {
    let d = Daemon::new();
    for (mac, name) in [(A, "Ditoo-Plus"), (B, "Pixoo64")] {
        let reply = d
            .handle(make_request(
                "connect",
                Some(json!({"mock": true, "mac": mac, "name": name})),
                None,
            ))
            .await;
        assert_eq!(reply["success"], json!(true), "{reply}");
    }
    let reply = d
        .handle(make_request("select_device", Some(json!({"mac": B})), None))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    d
}

async fn sent_by(d: &Daemon, mac: &str) -> usize {
    let dev = d.fleet.get(mac).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    match &*transport {
        DeviceTransport::Mock(m) => sent_count(m),
        _ => panic!("expected the mock transport"),
    }
}

fn sent_count(m: &MockTransport) -> usize {
    m.sent_commands.lock().map(|c| c.len()).unwrap_or_default()
}

async fn call(d: &Daemon, method: &str, args: Value, kwargs: Value, mac: &str) -> Value {
    d.handle(make_request(
        "device_call",
        Some(json!({"method": method, "args": args, "kwargs": kwargs, "mac": mac})),
        None,
    ))
    .await
}

#[tokio::test]
async fn every_channel_write_lands_on_the_named_panel_not_the_selected_one() {
    let writes = [
        ("display.switch_channel", json!(["vj"]), json!({})),
        (
            "display.show_clock",
            json!([]),
            json!({"clock": 3, "color": "#ff0000"}),
        ),
        ("display.show_effects", json!([]), json!({"number": 4})),
        (
            "display.show_visualization",
            json!([]),
            json!({"number": 5}),
        ),
        (
            "display.show_light",
            json!(["#00ffcc", 80, true, 0]),
            json!({}),
        ),
        ("scoreboard.set_scoreboard", json!([1, 3, 5]), json!({})),
    ];
    for (method, args, kwargs) in writes {
        let d = two_panels_with_b_selected().await;
        let reply = call(&d, method, args, kwargs, A).await;
        assert_eq!(reply["success"], json!(true), "{method}: {reply}");
        assert!(sent_by(&d, A).await > 0, "{method} never reached A");
        assert_eq!(
            sent_by(&d, B).await,
            0,
            "{method} reached B, the selected panel"
        );
    }
}

#[tokio::test]
async fn a_channel_switch_is_recorded_on_the_named_panel() {
    let d = two_panels_with_b_selected().await;
    let reply = call(&d, "display.switch_channel", json!(["vj"]), json!({}), A).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let act = d
        .handle(make_request("get_device_activity", None, None))
        .await;
    assert_eq!(act["activity"][A]["kind"], json!("vj"), "{act}");
    assert!(act["activity"].get(B).is_none(), "{act}");
}
