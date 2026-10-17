//! `get_topology` lists every screen with its size and live link (P4.2).
//!
//! `list_screens` forwards `get_topology`, which returned the saved layout
//! (x/y/room per address) and one `current_device` -- no resolution and no
//! per-panel link state, so an agent could not tell a linked 64x64 panel from
//! a 16x16 one that was unplugged last week. Its own binary: the layout path
//! is an environment variable, and no other test may see it set.

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::{json, Value};

fn screen<'a>(reply: &'a Value, mac: &str) -> &'a Value {
    reply["screens"]
        .as_array()
        .and_then(|s| {
            s.iter().find(|e| {
                e["mac"]
                    .as_str()
                    .is_some_and(|m| m.eq_ignore_ascii_case(mac))
            })
        })
        .unwrap_or_else(|| panic!("{mac} not listed: {reply}"))
}

#[tokio::test]
async fn every_screen_carries_its_size_link_and_place() {
    let dir = std::env::temp_dir().join(format!("divoomd_screens_{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("temp dir");
    let layout = dir.join("topology.json");
    std::fs::write(
        &layout,
        json!({
            "devices": {
                "aa:bb": {"x": 1, "y": 2, "room": "Desk"},
                "ZZ": {"x": 5, "y": 0, "room": "Den"}
            },
            "rooms": ["Desk", "Den"],
            "wall_linked": true
        })
        .to_string(),
    )
    .expect("write layout");
    std::env::set_var("DIVOOM_TOPOLOGY_PATH", &layout);

    let d = Daemon::new();
    for (mac, name) in [("AA:BB", "Pixoo64-light"), ("CC", "Tivoo-Max-light")] {
        let r = d
            .handle(make_request(
                "connect",
                Some(json!({ "mock": true, "mac": mac, "name": name })),
                None,
            ))
            .await;
        assert_eq!(r["success"], json!(true), "{r}");
    }
    let reply = d.handle(make_request("get_topology", None, None)).await;
    assert_eq!(reply["success"], json!(true), "{reply}");

    let placed = screen(&reply, "AA:BB");
    assert_eq!(placed["connected"], true, "{placed}");
    assert_eq!(placed["width"], 64, "{placed}");
    assert_eq!(placed["x"], 1, "{placed}");
    assert_eq!(placed["room"], "Desk", "{placed}");

    let unplaced = screen(&reply, "CC");
    assert_eq!(unplaced["width"], 16, "{unplaced}");
    assert_eq!(
        unplaced["x"],
        Value::Null,
        "linked but never placed: {unplaced}"
    );

    let absent = screen(&reply, "ZZ");
    assert_eq!(absent["connected"], false, "{absent}");
    assert_eq!(
        absent["width"],
        Value::Null,
        "an unseen panel's size is unknown: {absent}"
    );
    assert_eq!(absent["room"], "Den", "{absent}");

    let _ = std::fs::remove_file(&layout);
}
