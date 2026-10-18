//! A wall reply names the panel that failed (P6.3).
//!
//! A wall command whose write failed on a linked panel used to answer
//! `device_failed` with `degraded: []`: the wall's per-command methods
//! returned one `bool` for every slot, and `degraded` named only slots with
//! no panel. A client could not tell which panel of the wall did not take the
//! command. Each wall method now returns one outcome per slot, and the reply
//! names every slot whose write failed (`failed`, with the reason) apart from
//! every slot with no panel (`degraded`).

use crate::daemon::{Daemon, DeviceTransport};
use crate::mock_transport::MockTransport;
use crate::protocol::make_request;
use crate::socket_server::Handler;
use crate::wall::{DeviceSlot, DivoomWall};
use serde_json::{json, Value};
use std::sync::Arc;

pub const A: &str = "AA:00:00:00:00:01";
pub const B: &str = "BB:00:00:00:00:02";
const C: &str = "CC:00:00:00:00:03";

pub async fn two_panel_wall() -> Daemon {
    let d = Daemon::new();
    for mac in [A, B] {
        let reply = d
            .handle(make_request(
                "connect",
                Some(json!({"mock": true, "mac": mac, "name": "Ditoo-Plus"})),
                None,
            ))
            .await;
        assert_eq!(reply["success"], json!(true), "{reply}");
    }
    let slots = json!({"slots": {
        A: {"x": 0, "y": 0, "size": 16},
        B: {"x": 1, "y": 0, "size": 16},
    }});
    let reply = d
        .handle(make_request("wall_configure", Some(slots), None))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    d
}

pub async fn mock_of(d: &Daemon, mac: &str) -> MockTransport {
    let dev = d.fleet.get(mac).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    match &*transport {
        DeviceTransport::Mock(m) => m.clone(),
        _ => panic!("expected the mock transport"),
    }
}

pub async fn wall_call(d: &Daemon, method: &str, args: Value) -> Value {
    d.handle(make_request(
        "device_call",
        Some(json!({"method": method, "target": "wall", "args": args})),
        None,
    ))
    .await
}

/// A fresh image file per call: tests run concurrently, and one test
/// rewriting a shared path while another's wall reads it fails that read.
fn a_png() -> String {
    static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let name = format!("divoom_wall_outcome_{}_{n}.png", std::process::id());
    let path = std::env::temp_dir().join(name);
    image::RgbImage::from_pixel(32, 16, image::Rgb([200, 40, 10]))
        .save(&path)
        .expect("write the test image");
    path.to_string_lossy().into_owned()
}

/// Every command the wall dispatches, with arguments it accepts.
fn every_wall_call() -> Vec<(&'static str, Value)> {
    vec![
        ("show_image", json!([a_png()])),
        ("show_light", json!(["#FF0000", 50])),
        ("show_clock", json!([1])),
        ("set_clock_rich", json!([2])),
        ("set_scoreboard", json!([1, 3, 4])),
        ("show_effects", json!([2])),
        ("show_visualization", json!([3])),
        ("set_brightness", json!([40])),
        ("set_volume", json!([5])),
        ("switch_channel", json!(["clock"])),
    ]
}

fn remove_images(calls: &[(&str, Value)]) {
    for (_, args) in calls.iter().filter(|(m, _)| *m == "show_image") {
        if let Some(path) = args[0].as_str() {
            let _ = std::fs::remove_file(path);
        }
    }
}

fn failed_macs(reply: &Value) -> Vec<String> {
    reply["failed"]
        .as_object()
        .map(|m| m.keys().cloned().collect())
        .unwrap_or_default()
}

#[tokio::test]
async fn every_wall_call_names_exactly_the_panel_whose_write_failed() {
    let d = two_panel_wall().await;
    mock_of(&d, B).await.set_failing(true);
    let calls = every_wall_call();
    for (method, args) in calls.clone() {
        let reply = wall_call(&d, method, args).await;
        assert_eq!(reply["success"], json!(false), "{method}: {reply}");
        assert_eq!(reply["code"], json!("device_failed"), "{method}: {reply}");
        assert_eq!(
            failed_macs(&reply),
            vec![B.to_string()],
            "{method}: {reply}"
        );
        let why = reply["failed"][B].as_str().unwrap_or_default();
        assert!(!why.is_empty(), "{method}: the reason is kept: {reply}");
        assert_eq!(
            reply["degraded"],
            json!([]),
            "{method}: B is linked: {reply}"
        );
        let error = reply["error"].as_str().unwrap_or_default();
        assert!(error.contains(B), "{method}: the message names B: {reply}");
        assert!(!error.contains(A), "{method}: A took it: {reply}");
    }
    remove_images(&calls);
}

#[tokio::test]
async fn a_wall_whose_panels_all_take_it_succeeds() {
    let d = two_panel_wall().await;
    let calls = every_wall_call();
    for (method, args) in calls.clone() {
        let reply = wall_call(&d, method, args).await;
        assert_eq!(reply["success"], json!(true), "{method}: {reply}");
    }
    remove_images(&calls);
}

#[tokio::test]
async fn a_slot_with_no_panel_and_a_failed_write_are_told_apart() {
    let d = two_panel_wall().await;
    let failing = mock_of(&d, B).await;
    failing.set_failing(true);
    let slot = |mac: &str, x: i32, device: Option<Arc<DeviceTransport>>| DeviceSlot {
        device,
        mac: mac.to_string(),
        x,
        y: 0,
        size: 16,
        width: None,
        height: None,
    };
    let mock = |m: MockTransport| Some(Arc::new(DeviceTransport::Mock(m)));
    *d.wall.lock().await = Some(DivoomWall {
        devices: vec![
            slot(A, 0, mock(mock_of(&d, A).await)),
            slot(B, 1, mock(failing)),
            slot(C, 2, None),
        ],
        refused: Vec::new(),
        total_width: 48,
        total_height: 16,
        min_x: 0,
        min_y: 0,
        grid_unit_size: 16,
        is_free_form: false,
        previews: Arc::default(),
    });
    let reply = wall_call(&d, "set_brightness", json!([40])).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(failed_macs(&reply), vec![B.to_string()], "{reply}");
    assert_eq!(reply["degraded"], json!([C]), "{reply}");
    let error = reply["error"].as_str().unwrap_or_default();
    assert!(error.contains(B) && error.contains(C), "{reply}");
}

/// The wall's channel names are the panel's: the GUI sends one name to either.
#[tokio::test]
async fn the_wall_switches_to_every_channel_one_panel_does() {
    let d = two_panel_wall().await;
    let last_sent = |m: &MockTransport| m.sent_commands.lock().ok().and_then(|c| c.last().cloned());
    let (a, b) = (mock_of(&d, A).await, mock_of(&d, B).await);
    for name in [
        "clock",
        "visualizer",
        "eq",
        "vj",
        "design",
        "custom",
        "scoreboard",
        "cloud",
        "hot",
        "ambient",
        "lighting",
    ] {
        let one = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": "display.switch_channel", "args": [name], "mac": A})),
                None,
            ))
            .await;
        assert_eq!(one["success"], json!(true), "{name}: {one}");
        let panel_bytes = last_sent(&a);
        let reply = wall_call(&d, "switch_channel", json!([name])).await;
        assert_eq!(reply["success"], json!(true), "{name}: {reply}");
        assert_eq!(
            last_sent(&a),
            panel_bytes,
            "{name}: the wall sends what one panel does"
        );
        assert_eq!(last_sent(&b), panel_bytes, "{name}: to every slot");
    }
    let reply = wall_call(&d, "switch_channel", json!(["zz"])).await;
    assert_eq!(reply["code"], json!("bad_request"), "{reply}");
}

/// The wall's rich clock and scoreboard are a panel's (P6.5): the GUI sent
/// both to the wall, which refused them `unsupported` until they were routed
/// through the parsers one panel uses.
#[tokio::test]
async fn the_wall_sends_a_panels_clock_and_scoreboard_bytes() {
    let d = two_panel_wall().await;
    let last_sent = |m: &MockTransport| m.sent_commands.lock().ok().and_then(|c| c.last().cloned());
    let (a, b) = (mock_of(&d, A).await, mock_of(&d, B).await);
    let calls = [
        (
            "display.set_clock_rich",
            json!({"style": 3, "date": true, "color": "#00FF00"}),
        ),
        (
            "scoreboard.set_scoreboard",
            json!({"on_off": 1, "red_score": 7, "blue_score": 9}),
        ),
    ];
    for (method, kwargs) in calls {
        let one = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": method, "kwargs": kwargs, "mac": A})),
                None,
            ))
            .await;
        assert_eq!(one["success"], json!(true), "{method}: {one}");
        let panel_bytes = last_sent(&a);
        let reply = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": method, "target": "wall", "kwargs": kwargs})),
                None,
            ))
            .await;
        assert_eq!(reply["success"], json!(true), "{method}: {reply}");
        assert_eq!(
            last_sent(&a),
            panel_bytes,
            "{method}: the wall sends what one panel does"
        );
        assert_eq!(last_sent(&b), panel_bytes, "{method}: to every slot");
    }
    let reply = wall_call(&d, "set_scoreboard", json!([1, 5000, 0])).await;
    assert_eq!(
        reply["code"],
        json!("bad_request"),
        "a score out of bounds is refused: {reply}"
    );
}

/// `connect`'s mock `failing` links a panel whose every write fails, so a
/// test through the socket (`tests/test_e2e_wall_write_names_the_panel.py`)
/// can see the wall name it (P6.4).
#[tokio::test]
async fn a_panel_linked_failing_is_named_by_the_wall() {
    let d = Daemon::new();
    for (mac, failing) in [(A, false), (B, true)] {
        let reply = d
            .handle(make_request(
                "connect",
                Some(json!({"mock": true, "mac": mac, "failing": failing})),
                None,
            ))
            .await;
        assert_eq!(reply["success"], json!(true), "{reply}");
    }
    let slots =
        json!({"slots": {A: {"x": 0, "y": 0, "size": 16}, B: {"x": 1, "y": 0, "size": 16}}});
    let reply = d
        .handle(make_request("wall_configure", Some(slots), None))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let reply = wall_call(&d, "show_clock", json!([1])).await;
    assert_eq!(failed_macs(&reply), vec![B.to_string()], "{reply}");
}
