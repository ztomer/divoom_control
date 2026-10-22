//! `device_status` says what each panel is: model and resolution (P3.1).
//!
//! Through the real daemon dispatcher, with mock panels advertising real
//! names -- one per pixel class -- plus a name nothing matches, read back both
//! from the fleet summary and per panel.

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::{json, Value};

async fn connect(d: &Daemon, mac: &str, name: &str) {
    let r = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": mac, "name": name })),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");
}

fn entry<'a>(status: &'a Value, mac: &str) -> &'a Value {
    status["devices"]
        .as_array()
        .and_then(|ds| ds.iter().find(|d| d["mac"] == mac))
        .unwrap_or_else(|| panic!("{mac} not listed: {status}"))
}

#[tokio::test]
async fn every_listed_panel_carries_its_model_and_resolution() {
    let d = Daemon::new();
    let panels = [
        (
            "P16",
            "Tivoo-Max-light",
            json!("TivooMax"),
            json!(16),
            "name",
        ),
        (
            "P32",
            "Pixoo-Max-light",
            json!("PIXOO_MAX"),
            json!(32),
            "name",
        ),
        (
            "P64",
            "Pixoo64-light",
            json!("Pixoo64Wifi"),
            json!(64),
            "name",
        ),
        (
            "P128",
            "Divoom MiniToo",
            json!("MiniToo"),
            json!(128),
            "name",
        ),
        (
            "P256",
            "Divoom Emodo",
            json!("DigitalBadge"),
            json!(256),
            "name",
        ),
        ("PX", "SomethingElse", Value::Null, json!(16), "default"),
    ];
    for (mac, name, ..) in &panels {
        connect(&d, mac, name).await;
    }

    let fleet = d.handle(make_request("device_status", None, None)).await;
    for (mac, _, model, px, source) in &panels {
        let e = entry(&fleet, mac);
        assert_eq!(e["model"], *model, "{e}");
        assert_eq!(e["width"], *px, "{e}");
        assert_eq!(e["height"], *px, "{e}");
        assert_eq!(e["model_source"], *source, "{e}");
    }

    // Asked about one panel, the reply describes that panel.
    let one = d
        .handle(make_request(
            "device_status",
            Some(json!({ "mac": "P64" })),
            None,
        ))
        .await;
    assert_eq!(one["model"], "Pixoo64Wifi", "{one}");
    assert_eq!(one["width"], 64, "{one}");
}

/// P4.1: each entry also says what the vendor app enables for that model --
/// and says nothing, rather than a guess, for a panel it cannot name.
#[tokio::test]
async fn every_listed_panel_carries_the_features_of_its_model() {
    let d = Daemon::new();
    connect(&d, "TM", "Tivoo-Max-light").await;
    connect(&d, "P64", "Pixoo64-light").await;
    connect(&d, "PX", "SomethingElse").await;
    let fleet = d.handle(make_request("device_status", None, None)).await;

    let tm = &entry(&fleet, "TM")["features"];
    assert_eq!(tm["speaker"], true, "{tm}");
    assert_eq!(tm["sd_card"], true, "{tm}");
    assert_eq!(tm["wifi"], false, "{tm}");
    let p64 = &entry(&fleet, "P64")["features"];
    assert_eq!(p64["wifi"], true, "{p64}");
    assert_eq!(p64["speaker"], false, "{p64}");
    assert_eq!(entry(&fleet, "PX")["features"], Value::Null, "{fleet}");
}

/// P3.4: the radio is the vendor app's per-model statement, so it is in the
/// description -- the Tivoo Max has none, the Tiivoo 2 has one.
#[tokio::test]
async fn the_radio_is_in_the_description_of_the_panel() {
    let d = Daemon::new();
    connect(&d, "TM", "Tivoo-Max-light").await;
    connect(&d, "T2", "Divoom Tiivoo 2").await;
    let fleet = d.handle(make_request("device_status", None, None)).await;

    assert_eq!(entry(&fleet, "TM")["features"]["radio"], false, "{fleet}");
    assert_eq!(entry(&fleet, "T2")["features"]["radio"], true, "{fleet}");
}

/// P3.4: what the panel CAN SHOW -- the app's own home list for its model.
#[tokio::test]
async fn the_screens_the_app_offers_are_in_the_description() {
    let d = Daemon::new();
    connect(&d, "TM", "Tivoo-Max-light").await;
    connect(&d, "T2", "Divoom Tiivoo 2").await;
    let fleet = d.handle(make_request("device_status", None, None)).await;

    let tm = entry(&fleet, "TM")["screens"].as_array().expect("a list");
    assert!(tm.iter().any(|s| s == "weather"), "{tm:?}");
    assert!(tm.iter().any(|s| s == "alarm"), "{tm:?}");
    assert!(!tm.iter().any(|s| s == "fm_radio"), "{tm:?}");
    // The Tiivoo 2 is one of the two panels the app offers an FM radio to.
    let t2 = entry(&fleet, "T2")["screens"].as_array().expect("a list");
    assert!(t2.iter().any(|s| s == "fm_radio"), "{t2:?}");
}

/// P3.4: the chassis -- which product the panel is and how big it is -- is the
/// daemon's, not the web UI's table.
#[tokio::test]
async fn the_chassis_is_in_the_description_of_the_panel() {
    let d = Daemon::new();
    connect(&d, "DI", "Ditoo-light-2").await;
    connect(&d, "TM", "Tivoo-Max-light-3").await;
    connect(&d, "PX", "SomethingElse").await;
    let fleet = d.handle(make_request("device_status", None, None)).await;

    assert_eq!(entry(&fleet, "DI")["chassis"]["family"], "ditoo", "{fleet}");
    assert_eq!(entry(&fleet, "DI")["chassis"]["screen_mm"], 64.0, "{fleet}");
    assert_eq!(
        entry(&fleet, "TM")["chassis"]["family"],
        "tivoo_max",
        "{fleet}"
    );
    // A panel nobody can name is the generic chassis, never a guess.
    assert_eq!(entry(&fleet, "PX")["chassis"]["family"], "panel", "{fleet}");
}

/// P3.4: the daemon is the one place that knows a panel has no radio, so the
/// daemon is the one place that refuses to tune one.
#[tokio::test]
async fn a_panel_with_no_radio_is_refused_the_tuning() {
    let d = Daemon::new();
    connect(&d, "DI", "Ditoo-light-2").await;
    let r = d
        .handle(make_request(
            "device_call",
            Some(json!({ "method": "radio.set_radio_frequency", "kwargs": { "freq_x10": 911 } })),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(false), "{r}");
    assert_eq!(r["code"], "unsupported", "{r}");
    assert!(
        r["error"].as_str().unwrap_or("").contains("no FM radio"),
        "{r}"
    );
}

/// ...and a panel that HAS one is tuned, and one the daemon cannot name is
/// not refused: unknown is not "no radio".
#[tokio::test]
async fn a_panel_with_a_radio_is_tuned_and_an_unknown_one_is_not_refused() {
    let d = Daemon::new();
    connect(&d, "T2", "Divoom Tiivoo 2").await;
    let ok = d
        .handle(make_request(
            "device_call",
            Some(json!({ "method": "radio.set_radio_frequency", "kwargs": { "freq_x10": 911 } })),
            None,
        ))
        .await;
    assert_eq!(ok["success"], json!(true), "{ok}");

    let d2 = Daemon::new();
    connect(&d2, "PX", "SomethingElse").await;
    let unknown = d2
        .handle(make_request(
            "device_call",
            Some(json!({ "method": "radio.set_radio_frequency", "kwargs": { "freq_x10": 911 } })),
            None,
        ))
        .await;
    assert_eq!(unknown["success"], json!(true), "{unknown}");
}
