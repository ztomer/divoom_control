//! What the daemon holds comes back after it restarts (P2.7's remainder).
//!
//! The GUI's relink (`divoom_gui/panel_relink.py`) brings back the panels the
//! GUI itself linked — and only those. A panel a CLI or an MCP client linked
//! had no client left holding the memory, and a wall's slots were never a
//! link at all, so both stayed dark after a daemon restart until a human
//! clicked.
//!
//! So the daemon writes down what it holds and replays it on startup. These
//! tests are the wire-level proof: a link the daemon took is in the saved
//! list, a NEW daemon reads that list and links the panel again, and a panel
//! the user dropped is not in it.

use divoomd::daemon::Daemon;
use divoomd::links;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

/// A daemon that keeps its list in a file of its own.
///
/// The list is NAMED (the app's `DIVOOM_LINKS_PATH` names one the same way),
/// and a named list may hold a mock panel: a test double belongs in a test's
/// file, never in the user's. The location is built directly rather than
/// through the environment variable, because that variable is process-wide and
/// these tests run in parallel.
fn daemon_with_own_list(dir: &std::path::Path) -> Daemon {
    let mut daemon = Daemon::new();
    daemon.persist_links(links::Location {
        path: dir.join("links.json"),
        named: true,
    });
    daemon
}

/// The list a daemon would write, read back as JSON.
fn saved_list(dir: &std::path::Path) -> serde_json::Value {
    let text = std::fs::read_to_string(dir.join("links.json")).expect("the daemon wrote no list");
    serde_json::from_str(&text).expect("the list is not JSON")
}

#[tokio::test]
async fn a_panel_the_daemon_held_is_linked_again_after_a_restart() {
    let dir = tempfile::tempdir().expect("temp dir");

    // A client links a panel — the CLI's path, and the MCP server's: both
    // go through the same `connect` command.
    let first = daemon_with_own_list(dir.path());
    let reply = first
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true));

    // The daemon restarts: a NEW daemon reads the list the old one wrote.
    let saved = saved_list(dir.path());
    assert_eq!(saved["links"][0]["id"], json!("DEV_A"));

    let second = daemon_with_own_list(dir.path());
    links::restore(&second).await;
    assert!(
        second.fleet.connected("DEV_A").await.is_some(),
        "the panel the daemon held came back"
    );
}

#[tokio::test]
async fn a_panel_the_user_dropped_does_not_come_back() {
    let dir = tempfile::tempdir().expect("temp dir");

    let first = daemon_with_own_list(dir.path());
    first
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    // The user drops it.
    let dropped = first
        .handle(make_request(
            "disconnect",
            Some(json!({"mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(dropped["success"], json!(true));

    let saved = saved_list(dir.path());
    assert!(
        saved["links"].as_array().is_none_or(Vec::is_empty),
        "a dropped panel is not in the list: {saved}"
    );

    let second = daemon_with_own_list(dir.path());
    links::restore(&second).await;
    assert!(
        second.fleet.connected("DEV_A").await.is_none(),
        "a panel the user dropped stayed dropped"
    );
}

#[tokio::test]
async fn the_wall_comes_back_after_a_restart() {
    let dir = tempfile::tempdir().expect("temp dir");

    let first = daemon_with_own_list(dir.path());
    first
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    let wall = first
        .handle(make_request(
            "wall_configure",
            Some(json!({
                "slots": {"DEV_A": {"x": 0, "y": 0, "size": 16}},
                "cell_size": 16
            })),
            None,
        ))
        .await;
    assert_eq!(wall["success"], json!(true));

    // The wall's slots are in the list: a wall is not a link, so nothing
    // else would bring it back.
    let saved = saved_list(dir.path());
    assert_eq!(saved["wall"]["slots"]["DEV_A"]["size"], json!(16));

    let second = daemon_with_own_list(dir.path());
    links::restore(&second).await;
    let restored = second
        .handle(make_request("get_topology", Some(json!({})), None))
        .await;
    assert_eq!(restored["wall_active"], json!(true));
    assert_eq!(restored["slots"]["DEV_A"]["size"], json!(16));
}

#[tokio::test]
async fn a_teardown_wall_is_not_brought_back() {
    let dir = tempfile::tempdir().expect("temp dir");

    let first = daemon_with_own_list(dir.path());
    first
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    first
        .handle(make_request(
            "wall_configure",
            Some(json!({"slots": {"DEV_A": {"x": 0, "y": 0, "size": 16}}})),
            None,
        ))
        .await;
    // The user takes the wall down.
    let down = first
        .handle(make_request(
            "wall_configure",
            Some(json!({"slots": {}})),
            None,
        ))
        .await;
    assert_eq!(down["success"], json!(true));

    let saved = saved_list(dir.path());
    assert!(
        saved.get("wall").is_none_or(serde_json::Value::is_null),
        "a torn-down wall is not in the list: {saved}"
    );
}
