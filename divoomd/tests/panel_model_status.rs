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
