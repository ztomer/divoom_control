//! The per-panel hot-channel verdict's rules (U.5), pinned without a radio.

use super::*;
use serde_json::json;

fn tmp_state() -> (tempfile::TempDir, std::path::PathBuf) {
    let dir = tempfile::TempDir::new().unwrap();
    let path = dir.path().join("hotchannel_state.json");
    (dir, path)
}

fn ok_run(at: u64) -> Verdict {
    Verdict::from_hot_update(
        RunBy::Button,
        at,
        &Ok(json!({"served": [], "manifest": 23, "downloaded": 23})),
    )
}

#[test]
fn a_failure_replaces_the_earlier_success() {
    let (_d, path) = tmp_state();
    record_at(&path, "P", &ok_run(100)).unwrap();
    let failed = Verdict {
        at: 200,
        by: RunBy::Schedule,
        error: Some("could not connect".into()),
        offered: 0,
        fetched: 0,
        delivered: 0,
    };
    record_at(&path, "p", &failed).unwrap();
    let panels = load(&path)["panels"].as_object().cloned().unwrap();
    assert_eq!(
        panels.len(),
        1,
        "one record per panel, whatever its case: {panels:?}"
    );
    let v = &panels["p"];
    assert_eq!(v["outcome"], json!("failed"));
    assert_eq!(v["error"], json!("could not connect"));
    assert_eq!(v["by"], json!("schedule"));
    assert_eq!(v["at"], json!(200));
}

#[test]
fn the_schedules_own_keys_and_the_verdicts_never_overwrite_each_other() {
    let (_d, path) = tmp_state();
    record_at(&path, "P", &ok_run(100)).unwrap();
    update_at(&path, |s| {
        s.insert("last_outcome".into(), json!("failed"));
        s.insert("last_run_utc".into(), json!(300));
    })
    .unwrap();
    let state = load(&path);
    assert_eq!(state["last_outcome"], json!("failed"));
    assert_eq!(state["panels"]["P"]["offered"], json!(23), "{state:?}");
}

#[test]
fn each_path_maps_onto_the_one_record() {
    let ok = Verdict::from_hot_update(
        RunBy::SyncNow,
        5,
        &Ok(json!({"served": ["a", "b", "c"], "manifest": 23, "downloaded": 19})),
    );
    assert_eq!((ok.offered, ok.fetched, ok.delivered), (23, 19, 3));
    assert_eq!(ok.to_json()["outcome"], json!("ok"));
    assert_eq!(ok.to_json()["by"], json!("sync_now"));

    let err = Verdict::from_hot_update(RunBy::Button, 5, &Err("boom".into()));
    assert_eq!(err.to_json()["outcome"], json!("failed"));
    assert_eq!(err.to_json()["error"], json!("boom"));

    let device = DeviceOutcome {
        address: "P".into(),
        classify: 18,
        files: 5,
        pushed: 5,
        stored: 3,
        error: None,
        warnings: vec!["x".into()],
    };
    let sched = Verdict::from_schedule(9, &device);
    assert_eq!((sched.offered, sched.fetched, sched.delivered), (5, 5, 3));
    assert_eq!(sched.by, RunBy::Schedule);
}

#[test]
fn a_request_names_the_button_or_sync_now_and_never_the_schedule() {
    assert_eq!(RunBy::from_request(None), Some(RunBy::Button));
    assert_eq!(RunBy::from_request(Some("button")), Some(RunBy::Button));
    assert_eq!(RunBy::from_request(Some("sync_now")), Some(RunBy::SyncNow));
    assert_eq!(RunBy::from_request(Some("schedule")), None);
}

/// The owner's two records of 2026-10-31, folded into one: the newer of the
/// button's stamp and the schedule's entry wins per panel, the wall (no
/// panel) is not carried, `devices` goes and the old file is deleted.
#[test]
fn the_owners_two_records_become_one_verdict_per_panel() {
    let (dir, state) = tmp_state();
    let legacy = dir.path().join("hot_update_state.json");
    std::fs::write(
        &legacy,
        json!({
            "2b471aee": {"checked_at": 1_793_286_719_u64, "confirmed": 0, "downloaded": 23, "manifest": 23, "served": 0},
            "MatrixWall": {"checked_at": 1_788_832_127_u64, "confirmed": 2, "downloaded": 21, "manifest": 21, "served": 2},
            "e9a41e1e": {"checked_at": 1_793_286_510_u64, "confirmed": 5, "downloaded": 23, "manifest": 23, "served": 5},
            "newer-button": {"checked_at": 1_793_500_000_u64, "downloaded": 23, "manifest": 23, "served": 1}
        })
        .to_string(),
    )
    .unwrap();
    std::fs::write(
        &state,
        json!({
            "last_outcome": "failed",
            "last_run_utc": 1_793_468_518_u64,
            "devices": [
                {"address": "2b471aee", "error": "connect already in progress", "files": 0, "shown": 0, "stored": 0},
                {"address": "newer-button", "error": "connect already in progress", "files": 0, "shown": 0, "stored": 0}
            ]
        })
        .to_string(),
    )
    .unwrap();
    let discovered = dir.path().join("discovered_devices.json");
    std::fs::write(
        &discovered,
        json!([{"address": "2b471aee"}, {"address": "e9a41e1e"}, {"address": "newer-button"}])
            .to_string(),
    )
    .unwrap();
    let reported = crate::reported_panels::Reported::from_files(Some(&discovered), None);

    let carried = migrate_at(&state, &legacy, &reported).unwrap();
    assert_eq!(carried, 3);
    let s = load(&state);
    let panels = s["panels"].as_object().unwrap();
    assert_eq!(panels.len(), 3, "{panels:?}");
    assert!(!panels.contains_key("MatrixWall"), "the wall is no panel");
    // The schedule's failure is newer than the button's success.
    assert_eq!(panels["2b471aee"]["outcome"], json!("failed"));
    assert_eq!(panels["2b471aee"]["by"], json!("schedule"));
    // The button ran after the schedule here.
    assert_eq!(panels["newer-button"]["by"], json!("button"));
    assert_eq!(panels["newer-button"]["delivered"], json!(1));
    // Only the button ever ran on this one.
    assert_eq!(panels["e9a41e1e"]["outcome"], json!("ok"));
    assert_eq!(panels["e9a41e1e"]["at"], json!(1_793_286_510_u64));
    assert!(!s.contains_key("devices"), "{s:?}");
    assert_eq!(s["last_outcome"], json!("failed"), "the cadence keys stay");
    assert!(!legacy.exists(), "the old file is gone");

    // Once is once.
    assert_eq!(migrate_at(&state, &legacy, &reported).unwrap(), 0);
}

#[test]
fn the_event_names_its_panel() {
    let e = event("P", &ok_run(1));
    assert_eq!(e["type"], json!("hot_status"));
    assert_eq!(e["mac"], json!("P"));
    assert_eq!(e["verdict"]["outcome"], json!("ok"));
}
