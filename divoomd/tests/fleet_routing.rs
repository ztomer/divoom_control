//! Fleet routing: which panel a request goes to (2026-09-12).
//!
//! Split from `live_jobs_stress.rs` for the 500-line cap. The helpers are
//! the same small mock-connect ones; the invariant under test here is the
//! ACTIVE panel: explicit `mac`, else the active panel while it is linked,
//! else the single linked panel, else an honest refusal.
use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;
use std::sync::Arc;

async fn daemon_with_mock(mac: &str) -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": mac})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true), "mock connect: {conn}");
    assert!(
        d.encoder().is_some(),
        "these scenarios need the frame encoder: run scripts/build_libdivoom.sh"
    );
    d
}

/// Number of commands the mock behind `mac` has received so far.
async fn sent_count(d: &Daemon, mac: &str) -> usize {
    let t = d
        .fleet
        .get(mac)
        .await
        .expect("device known")
        .transport()
        .await
        .expect("device connected");
    match &*t {
        DeviceTransport::Mock(m) => m.sent_commands.lock().unwrap().len(),
        _ => panic!("expected a mock transport"),
    }
}

async fn daemon_with_mock_on(d: &Daemon, mac: &str) -> serde_json::Value {
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": mac})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true), "mock reconnect: {conn}");
    conn
}

#[tokio::test]
async fn a_macless_call_goes_to_the_selected_panel_and_is_refused_when_none_is() {
    // "Whichever connected last" is gone. The ACTIVE panel (first to link,
    // then whatever `select_device` says) takes a mac-less call; with
    // several linked and none selected, the caller is told there are several
    // and nothing is sent to any of them.
    let d = daemon_with_mock("DEV_A").await;
    daemon_with_mock_on(&d, "DEV_B").await;
    let switch = |mac: Option<&str>| {
        let mut args = json!({"method": "display.switch_channel", "kwargs": {"channel": "clock"}});
        if let Some(m) = mac {
            args["mac"] = json!(m);
        }
        make_request("device_call", Some(args), None)
    };
    let r = d.handle(switch(None)).await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert!(
        sent_count(&d, "DEV_A").await >= 1,
        "the first-linked panel is active"
    );
    assert_eq!(sent_count(&d, "DEV_B").await, 0);

    // The user picks B (bench click or menubar): every client hears it.
    let r = d
        .handle(make_request(
            "select_device",
            Some(json!({"mac": "dev_b"})),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");
    let st = d.handle(make_request("device_status", None, None)).await;
    assert_eq!(
        st["mac"],
        json!("DEV_B"),
        "mac-less status names the active panel: {st}"
    );
    assert_eq!(st["selected"], json!("dev_b"));
    let before_b = sent_count(&d, "DEV_B").await;
    let r = d.handle(switch(None)).await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert!(sent_count(&d, "DEV_B").await > before_b);

    // Named, it goes through -- and only there.
    let before_a = sent_count(&d, "DEV_A").await;
    let r = d.handle(switch(Some("dev_a"))).await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert!(sent_count(&d, "DEV_A").await > before_a);

    // The active panel is one the user selected but that is not linked
    // (they clicked an offline panel on the bench): with two others linked
    // the mac-less call is refused, naming the situation, and nothing is sent.
    let r = d
        .handle(make_request(
            "select_device",
            Some(json!({"mac": "DEV_OFFLINE"})),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");
    let a0 = sent_count(&d, "DEV_A").await;
    let b0 = sent_count(&d, "DEV_B").await;
    let r = d.handle(switch(None)).await;
    assert_eq!(r["success"], json!(false), "{r}");
    let err = r["error"].as_str().unwrap();
    assert!(
        err.starts_with("the active panel 'DEV_OFFLINE' is not connected"),
        "{err}"
    );
    assert_eq!(sent_count(&d, "DEV_A").await, a0);
    assert_eq!(sent_count(&d, "DEV_B").await, b0);
    // Mac-less status is the fleet, not a guess.
    let st = d.handle(make_request("device_status", None, None)).await;
    assert_eq!(st["connected"], json!(true));
    assert!(st["mac"].is_null(), "{st}");
    assert_eq!(st["selected"], json!("DEV_OFFLINE"));
    assert_eq!(st["devices"].as_array().unwrap().len(), 2);
    // Forgetting the active panel hands the slot to a linked one.
    let r = d
        .handle(make_request(
            "select_device",
            Some(json!({"mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true));
    let r = d
        .handle(make_request(
            "disconnect",
            Some(json!({"mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");
    let st = d.handle(make_request("device_status", None, None)).await;
    assert_eq!(st["selected"], json!("DEV_B"), "{st}");
    assert_eq!(st["mac"], json!("DEV_B"));
}

#[tokio::test]
async fn owned_devices_is_also_a_command_with_the_broadcast_shape() {
    // The menubar's polled fallback rebuilt the fleet from get_device_activity
    // and read "No active devices" with two idle panels linked. One shape,
    // on request and on the wire.
    let d = daemon_with_mock("DEV_A").await;
    daemon_with_mock_on(&d, "DEV_B").await;
    let r = d.handle(make_request("owned_devices", None, None)).await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert_eq!(r["type"], json!("owned_devices"));
    let devs = r["devices"].as_array().unwrap();
    assert_eq!(devs.len(), 2);
    let a = devs.iter().find(|x| x["address"] == "DEV_A").unwrap();
    assert_eq!(
        a["selected"],
        json!(true),
        "the first-linked panel is active: {r}"
    );
    assert_eq!(a["state"], json!("active"));
    assert_eq!(r["selected"], json!("DEV_A"));
}
