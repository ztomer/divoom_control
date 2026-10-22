//! Every other device action the GUI makes lands on the panel its
//! `device_call` names, not on the daemon's selected panel (P5.7).
//!
//! P5.6 pinned this for the channel writes (`mock_channel_tests.rs`). The
//! Tools tab (alarms, sleep, timer, countdown, noise, clock format, time sync,
//! name, power, radio, anniversary, orientation, factory reset, notification)
//! and the custom-art page switch named no panel, so they reached whichever
//! panel was selected when they arrived. They name it now; these pin that the
//! daemon honours the name over its own selection, with two mock panels and
//! the OTHER one selected. The method paths and arguments are the ones the
//! GUI sends (`divoom_gui/api/tools.py`).

use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::make_request;
use crate::socket_server::Handler;
use serde_json::{json, Value};

const A: &str = "AA:00:00:00:00:01";
const B: &str = "BB:00:00:00:00:02";

async fn two_panels_with_b_selected() -> Daemon {
    let d = Daemon::new();
    // A is the Tiivoo 2, because one of the actions below tunes the FM radio
    // and the daemon refuses that on a panel the vendor app says has no
    // radio (P3.4) -- and the refusal must not be mistaken for the action
    // not landing.
    for (mac, name) in [(A, "Divoom Tiivoo 2"), (B, "Pixoo64")] {
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
        DeviceTransport::Mock(m) => m.sent_commands.lock().map(|c| c.len()).unwrap_or_default(),
        _ => panic!("expected the mock transport"),
    }
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
async fn every_tools_action_lands_on_the_named_panel_not_the_selected_one() {
    let actions = [
        ("alarm.set_alarm", json!([2, 1, 7, 30, 31, 0, 0]), json!({})),
        (
            "sleep.show_sleep",
            json!([]),
            json!({"sleeptime": 20, "volume": 8, "color": [255, 0, 0], "on": 1}),
        ),
        ("timer.set_timer", json!([1]), json!({})),
        ("countdown.set_countdown", json!([0, 5, 30]), json!({})),
        ("noise.set_noise", json!([1]), json!({})),
        ("system.set_hour_type", json!([1]), json!({})),
        ("device.set_temp_type", json!([1]), json!({})),
        (
            "system.set_date_time",
            json!([]),
            json!({"year": 2026, "month": 10, "day": 18, "hour": 9, "minute": 5, "second": 0}),
        ),
        ("device.set_device_name", json!(["Desk"]), json!({})),
        ("device.set_auto_power_off", json!([60]), json!({})),
        ("device.set_low_power", json!([1]), json!({})),
        ("radio.set_radio_frequency", json!([1015]), json!({})),
        (
            "alarm.set_memorial_time",
            json!([0, 1, 12, 25, 9, 0, 1, "Xmas"]),
            json!({}),
        ),
        ("design.set_screen_dir", json!([2]), json!({})),
        ("design.set_screen_mirror", json!([true]), json!({})),
        ("design.factory_reset", json!([]), json!({})),
        ("notification.show_notification", json!([6]), json!({})),
        (
            "notification.show_notification_text",
            json!([7, "Hi"]),
            json!({}),
        ),
        ("design.use_user_define_index", json!([1]), json!({})),
    ];
    for (method, args, kwargs) in actions {
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
async fn a_rename_renames_the_named_panel() {
    let d = two_panels_with_b_selected().await;
    let reply = call(&d, "device.set_device_name", json!(["Desk"]), json!({}), A).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let a = call(&d, "device.get_device_name", json!([]), json!({}), A).await;
    let b = call(&d, "device.get_device_name", json!([]), json!({}), B).await;
    assert_eq!(a["result"], json!("Desk"), "{a}");
    assert_ne!(b["result"], json!("Desk"), "B was renamed: {b}");
}
