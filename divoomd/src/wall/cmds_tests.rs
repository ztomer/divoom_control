//! `wall/cmds.rs`'s tests (split out for the 500-line cap): the saved
//! layout's load, its merge, and the rooms it offers.

use super::*;

#[test]
fn test_topology_save_and_load() {
    let temp_dir = std::env::temp_dir().join("divoom_test_topology");
    let _ = std::fs::create_dir_all(&temp_dir);
    let file_path = temp_dir.join("test_topology.json");
    std::env::set_var("DIVOOM_TOPOLOGY_PATH", &file_path);

    let data = json!({
        "devices": {
            "11:22:33:44:55:01": {
                "name": "Ditoo Left",
                "model": "Ditoo Pro",
                "x": 30,
                "y": 40,
                "brightness": 85
            }
        },
        "wall_linked": true,
        "rooms": ["Desk"]
    });

    assert!(save_topology(&data).is_ok());
    let loaded = load_topology();
    assert_eq!(loaded["wall_linked"], true);
    assert_eq!(loaded["devices"]["11:22:33:44:55:01"]["name"], "Ditoo Left");
    assert_eq!(loaded["devices"]["11:22:33:44:55:01"]["brightness"], 85);

    let _ = std::fs::remove_file(&file_path);
    std::env::remove_var("DIVOOM_TOPOLOGY_PATH");
}

/// D.DV2: the owner's `topology.json` of 2026-10-31, read back -- the
/// invented fleet's four placements are dropped, the real panels and the
/// rooms kept.
#[test]
fn the_invented_fleet_is_dropped_from_the_owners_layout() {
    let tmp = tempfile::TempDir::new().unwrap();
    let discovered = tmp.path().join("discovered_devices.json");
    std::fs::write(
        &discovered,
        json!([{"address": "f90d2cc9-420e-65f9-9e06-f9554470fced"},
               {"address": "a9fccb71-3d3d-4de3-c381-0de382cdc4aa"}])
        .to_string(),
    )
    .unwrap();
    let reported = crate::reported_panels::Reported::from_files(Some(&discovered), None);
    let mut top = json!({"rooms": ["Desk", "Shelf"], "wall_linked": true, "devices": {
        "11:22:33:44:55:01": {"room": "Desk", "x": 50, "y": 100},
        "11:22:33:44:55:02": {"room": "Desk", "x": 91, "y": 101},
        "11:22:33:44:55:03": {"room": "Desk", "x": 157, "y": 86},
        "11:22:33:44:55:04": {"room": "Desk", "x": 228, "y": 10},
        "a9fccb71-3d3d-4de3-c381-0de382cdc4aa": {"room": "Shelf", "x": 681, "y": 39},
        "f90d2cc9-420e-65f9-9e06-f9554470fced": {"room": "Ethan", "x": 448, "y": 110}
    }});
    let dropped = retain_reported(&mut top, &reported);
    assert_eq!(dropped.len(), 4, "{dropped:?}");
    assert!(dropped.iter().all(|d| d.starts_with("11:22:33:44:55:")));
    let devs = top["devices"].as_object().unwrap();
    assert_eq!(devs.len(), 2, "{devs:?}");
    assert_eq!(top["rooms"], json!(["Desk", "Shelf"]), "rooms are kept");
}

/// The owner, 2026-11-01: the custom room "Ethan" was lost on a restart.
/// A GUI that had not loaded the daemon's copy sent its defaults
/// (Desk/Shelf/Wall), and `rooms` was a top-level key, so it REPLACED the
/// stored list. A room list merges; nothing a writer omits is removed.
#[test]
fn a_room_list_merges_and_never_replaces() {
    let stored = json!({"rooms": ["Desk", "Shelf", "Wall", "Ethan"], "devices": {}});
    let merged = merge_topology(stored, &json!({"rooms": ["Desk", "shelf", "Den"]}));
    assert_eq!(
        merged["rooms"],
        json!(["Desk", "Shelf", "Wall", "Ethan", "Den"]),
        "kept in the stored order and spelling, the new room appended"
    );
}

/// Removing a room is an explicit operation: it names the room, takes it
/// out of the list, and takes every panel out of it -- and is not itself
/// stored as a key of the layout.
#[test]
fn a_room_is_removed_only_by_naming_it() {
    let stored = json!({"rooms": ["Desk", "Shelf", "Ethan"], "devices": {
        "aa": {"room": "Ethan", "x": 1, "y": 2},
        "bb": {"room": "Shelf", "x": 3, "y": 4}
    }});
    let merged = merge_topology(stored, &json!({"remove_rooms": ["ethan"]}));
    assert_eq!(merged["rooms"], json!(["Desk", "Shelf"]));
    assert_eq!(
        merged["devices"]["aa"],
        json!({"x": 1, "y": 2}),
        "a panel in the removed room is in no room, and keeps its place"
    );
    assert_eq!(merged["devices"]["bb"]["room"], "Shelf");
    assert!(
        merged.get("remove_rooms").is_none(),
        "the operation is not stored: {merged}"
    );
}

/// A layout that was never saved names the rooms the GUI offers by
/// default -- the daemon is the one place that default lives.
#[test]
fn an_unsaved_layout_offers_the_default_rooms() {
    let tmp = tempfile::TempDir::new().unwrap();
    let missing = tmp.path().join("never_written.json");
    let top = load_topology_at(Some((missing, true)));
    assert_eq!(top["rooms"], json!(["Desk", "Shelf", "Wall"]));
}

#[test]
fn a_device_entry_replaces_the_stored_one_whole_and_whatever_its_case() {
    let stored = json!({"rooms": ["Desk", "Shelf"], "wall_linked": true, "devices": {
        "AA:BB:CC:00:00:01": {"room": "Shelf", "x": 1, "y": 2},
        "aa:bb:cc:00:00:02": {"room": "Shelf", "x": 3, "y": 4}
    }});
    let sent = json!({"devices": {"aa:bb:cc:00:00:01": {"x": 9, "y": 9}}});
    let merged = merge_topology(stored, &sent);
    let devs = merged["devices"].as_object().expect("devices");
    assert_eq!(
        devs.len(),
        2,
        "one key per panel, whatever its case: {devs:?}"
    );
    assert_eq!(
        merged["devices"]["aa:bb:cc:00:00:01"],
        json!({"x": 9, "y": 9}),
        "an entry sent without a room takes the panel out of its room"
    );
    assert_eq!(
        merged["devices"]["aa:bb:cc:00:00:02"]["room"], "Shelf",
        "other panels are kept"
    );
    assert_eq!(
        merged["rooms"],
        json!(["Desk", "Shelf"]),
        "keys not sent are kept"
    );
}
