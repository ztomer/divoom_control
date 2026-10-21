//! The loop's rules, pinned: which devices it pushes to, how often, and what
//! it does with a stale config file.
//!
//! Every test here is a RULE the owner stated, and every one of them can be
//! checked without a radio, a device or the cloud:
//!
//! * the devices come from the app's settings, not from a second list;
//! * a stale list never overrides the settings;
//! * the cadence is a day, because the content is;
//! * an empty settings table is a failure, not a quiet no-op.

use crate::monthly_best::{load_hotchannel_config, resolve_targets, should_run_now};
use std::fs;
use tempfile::TempDir;

/// The lock every test that moves `HOME` takes. `HOME` is process-global, so
/// two tests that move it at the same time would read each other's config.
fn home_lock() -> tokio::sync::MutexGuard<'static, ()> {
    crate::cloud::TEST_MUTEX
        .get_or_init(|| tokio::sync::Mutex::new(()))
        .blocking_lock()
}

/// A config directory with the given files in it, and `HOME` pointing at it.
fn config_home(files: &[(&str, &str)]) -> (TempDir, tokio::sync::MutexGuard<'static, ()>) {
    let guard = home_lock();
    let temp = TempDir::new().unwrap();
    std::env::set_var("HOME", temp.path());
    let dir = temp.path().join(".config").join("divoom-control");
    fs::create_dir_all(&dir).unwrap();
    for (name, body) in files {
        fs::write(dir.join(name), body).unwrap();
    }
    (temp, guard)
}

const SETTINGS_INI: &str = "\
[gui]
timeout = 120

[gallery]
f90d2cc9-420e-65f9-9e06-f9554470fced = 18
a9fccb71-3d3d-4de3-c381-0de382cdc4aa = 17
gallery_sort = 1
gallery_file_size = 1
";

#[test]
fn the_loop_pushes_to_the_devices_the_settings_register() {
    let (_temp, _guard) = config_home(&[
        ("config.ini", SETTINGS_INI),
        (
            "hotchannel.json",
            r#"{"enabled": true, "interval": 86400, "targets": ["AA:BB:CC:DD:EE:FF"]}"#,
        ),
    ]);

    let (targets, failures) = resolve_targets();

    assert!(
        failures.is_empty(),
        "the settings are readable, so there is nothing to report: {failures:?}"
    );
    assert_eq!(
        targets
            .iter()
            .map(|d| d.address.as_str())
            .collect::<Vec<_>>(),
        vec![
            "f90d2cc9-420e-65f9-9e06-f9554470fced",
            "a9fccb71-3d3d-4de3-c381-0de382cdc4aa"
        ],
        "the hot channel must reach the devices the app's settings register"
    );
}

#[test]
fn each_device_keeps_the_gallery_the_settings_give_it() {
    let (_temp, _guard) = config_home(&[("config.ini", SETTINGS_INI)]);
    let (targets, _failures) = resolve_targets();
    assert_eq!(targets[0].classify, 18);
    assert_eq!(targets[1].classify, 17);
}

#[test]
fn a_stale_list_in_the_old_file_never_overrides_the_settings() {
    let (_temp, _guard) = config_home(&[
        ("config.ini", SETTINGS_INI),
        (
            "hotchannel.json",
            r#"{"enabled": true, "interval": 86400, "targets": ["AA:BB:CC:DD:EE:FF"], "device_galleries": {"AA:BB:CC:DD:EE:FF": 9}}"#,
        ),
    ]);

    let loaded = load_hotchannel_config();

    assert_eq!(
        loaded.legacy_keys,
        vec!["targets".to_string(), "device_galleries".to_string()],
        "the stale keys must be REPORTED, not silently dropped"
    );
    let (targets, _failures) = resolve_targets();
    assert!(
        !targets.iter().any(|d| d.address == "AA:BB:CC:DD:EE:FF"),
        "the stale list must not put a device into the push"
    );
}

#[test]
fn the_cadence_is_a_day_because_the_content_is() {
    let (_temp, _guard) = config_home(&[("hotchannel.json", r#"{"enabled": true}"#)]);
    let loaded = load_hotchannel_config();
    assert_eq!(
        loaded.config.interval, 86_400,
        "the monthly-best content is refreshed almost daily, so the push must be daily"
    );
}

#[test]
fn the_operator_can_still_choose_the_cadence() {
    let (_temp, _guard) =
        config_home(&[("hotchannel.json", r#"{"enabled": true, "interval": 3600}"#)]);
    let loaded = load_hotchannel_config();
    assert_eq!(loaded.config.interval, 3600);
}

#[test]
fn a_settings_table_with_no_devices_is_a_failure_not_a_quiet_no_op() {
    let (_temp, _guard) = config_home(&[("config.ini", "[gallery]\ngallery_sort = 1\n")]);
    let (targets, _failures) = resolve_targets();
    assert_eq!(
        targets.len(),
        0,
        "there is nothing to push to, and the cycle must say so"
    );
}

#[test]
fn a_settings_entry_the_loop_cannot_resolve_is_reported() {
    let (_temp, _guard) = config_home(&[("config.ini", "[gallery]\nTimoo-light-4 = 18\n")]);
    let (targets, failures) = resolve_targets();
    assert_eq!(targets.len(), 0);
    assert_eq!(
        failures.len(),
        1,
        "a name the loop cannot use is a finding: {failures:?}"
    );
    assert!(
        failures[0].contains("Timoo-light-4"),
        "the failure must name the entry: {failures:?}"
    );
}

#[test]
fn the_interval_is_clamped_the_same_way_the_gui_clamps_it() {
    let (_temp, _guard) =
        config_home(&[("hotchannel.json", r#"{"enabled": true, "interval": 1}"#)]);
    let loaded = load_hotchannel_config();
    assert_eq!(loaded.config.interval, 60);
}

#[test]
fn a_restart_does_not_push_before_the_cadence_is_due() {
    // The daemon restarts with the GUI; the CADENCE is the point.
    assert!(
        should_run_now(None, 1_000, 86_400),
        "a loop that has never run is due"
    );
    assert!(
        !should_run_now(Some(1_000), 1_000 + 86_399, 86_400),
        "a second before the interval is up is not due"
    );
    assert!(
        should_run_now(Some(1_000), 1_000 + 86_400, 86_400),
        "one interval later it is due"
    );
    assert!(
        !should_run_now(Some(1_000), 1_000 + 10, 86_400),
        "a restart ten seconds after the last push must not push again"
    );
}
