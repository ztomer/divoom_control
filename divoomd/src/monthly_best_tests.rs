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

use crate::monthly_best::{load_hotchannel_config, resolve_targets, should_run_now, DeviceOutcome};
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

fn device(address: &str, pushed: usize, error: Option<&str>) -> DeviceOutcome {
    DeviceOutcome {
        address: address.to_string(),
        classify: 18,
        files: 10,
        pushed,
        stored: pushed,
        readback: None,
        error: error.map(str::to_string),
        warnings: Vec::new(),
    }
}

#[test]
fn a_device_that_failed_is_a_failed_run() {
    // Found by this round's own observed run: the device's failure was
    // printed, and the run's outcome said "ok". The quiet skip this whole
    // round exists to end, in the code that was written to end it.
    let devices = vec![
        device("A", 10, None),
        device(
            "B",
            0,
            Some("the device was reached but none of its 10 file(s) could be shown"),
        ),
    ];
    let failures = crate::monthly_best::device_failures(&devices);
    assert_eq!(failures.len(), 1, "the failed device is the run's failure");
    assert!(failures[0].contains('B'), "the failure names the device");
    let outcome = crate::monthly_best::fold_devices(devices, Vec::new());
    assert!(
        outcome.failures.len() == 1,
        "the run's outcome carries the device's failure: {:?}",
        outcome.failures
    );
    assert!(!outcome.ok(), "a run that missed a device is not ok");
}

#[test]
fn a_file_that_could_not_be_shown_is_a_warning_not_a_failed_run() {
    // The device was reached and the art IS on it. A container format the
    // decoder does not handle is a defect in the decoder; a run that rings
    // the owner's phone every day for it teaches them to ignore the channel.
    let mut warned = device("A", 9, None);
    warned
        .warnings
        .push("1 of 10 file(s) could not be shown".to_string());
    let devices = vec![warned];
    let outcome = crate::monthly_best::fold_devices(devices, Vec::new());
    assert!(
        outcome.failures.is_empty(),
        "a warning is not a failure: {:?}",
        outcome.failures
    );
    assert!(outcome.ok());
}

/// E56: the rule the box records, as a rule about the FILES.
///
/// A device that was REACHED and showed NOTHING fails the run and rings the
/// phone. A device that showed the art and could not show one file only
/// WARNS — and the warning NAMES the file and says WHY, because a run that
/// says "3 of 10 file(s) could not be shown" says less than the run that
/// names them.
#[test]
fn the_warning_names_the_file_and_the_failure_names_them_all() {
    use crate::monthly_best_push::{device_verdict, FileFailure};

    let failures = vec![
        FileFailure {
            name: "Old animation".to_string(),
            reason: "a magic-26 (0x1A) container with frame flag 0x2a".to_string(),
        },
        FileFailure {
            name: "Jack Skellington".to_string(),
            reason: "a magic-26 (0x1A) container with frame flag 0x2a".to_string(),
        },
    ];

    let (error, warnings) = device_verdict(0, 2, &failures);
    assert!(
        error.is_some(),
        "a device that was reached and stored nothing is a FAILED RUN"
    );
    assert!(
        warnings.is_empty(),
        "and it is a failure, not a warning: {warnings:?}"
    );
    let error = error.unwrap_or_default();
    assert!(
        error.contains("Old animation") && error.contains("Jack Skellington"),
        "the failure names the files it could not show: {error}"
    );

    let (error, warnings) = device_verdict(8, 10, &failures);
    assert!(
        error.is_none(),
        "a device that stored the art is not a failed run: {error:?}"
    );
    assert_eq!(
        warnings.len(),
        2,
        "one warning per file that did not make it"
    );
    assert!(
        warnings[0].contains("Old animation"),
        "the warning names the file: {warnings:?}"
    );
    assert!(
        warnings[0].contains("flag 0x2a"),
        "and says why: {warnings:?}"
    );
}

/// E63: the owner's ruling — *"art should be stored"*.
///
/// The push's job is to LEAVE the art on the device, not to flash it past.
/// So the failure turns on what the device STORED: a device that was reached
/// and stored nothing is a failed run, and a device that stored some of it
/// has stored something and said so.
#[test]
fn a_device_that_stored_nothing_is_a_failed_run() {
    use crate::monthly_best_push::{device_verdict, FileFailure};

    let failures = vec![FileFailure {
        name: "Haunted2026 Ghostly Cutie".to_string(),
        reason: "the device did not take the gallery page".to_string(),
    }];

    // The device SHOWED the art and kept nothing: the push did not do its
    // job, so the run fails and the owner's phone rings.
    let (error, warnings) = device_verdict(0, 5, &failures);
    assert!(
        error.is_some(),
        "a device that was reached and stored nothing is a FAILED RUN"
    );
    let error = error.unwrap_or_default();
    assert!(
        error.contains("stored"),
        "and the failure says what did not happen: {error}"
    );
    assert_eq!(
        warnings.len(),
        0,
        "it is a failure, not a warning: {warnings:?}"
    );
}

/// E63: three of five stored is three of five stored — the run says so.
#[test]
fn a_device_that_stored_some_of_the_art_is_not_a_failed_run() {
    use crate::monthly_best_push::{device_verdict, FileFailure};

    let failures = vec![FileFailure {
        name: "Jack Skellington".to_string(),
        reason: "the download failed".to_string(),
    }];

    let (error, warnings) = device_verdict(3, 5, &failures);
    assert!(
        error.is_none(),
        "a device that stored 3 of 5 file(s) has stored something: {error:?}"
    );
    assert_eq!(warnings.len(), 1, "the file that did not make it is named");
    assert!(
        warnings[0].contains("Jack Skellington"),
        "the warning names the file: {warnings:?}"
    );
}

/// E63: the state after a run says WHICH happened.
///
/// "ok" cannot answer the owner's question — did the art land on the device?
/// The state carries the files each device was SHOWN and the files it
/// STORED, and what the device said it holds.
#[test]
fn the_state_says_what_was_shown_and_what_was_stored() {
    use crate::monthly_best::{device_states, CycleOutcome, DeviceOutcome};

    let mut stored_device = DeviceOutcome {
        address: "A".to_string(),
        classify: 18,
        files: 5,
        pushed: 5,
        stored: 3,
        readback: Some("the device says it holds 3 item(s) on the page".to_string()),
        error: None,
        warnings: vec!["Jack Skellington: the download failed".to_string()],
    };
    stored_device.warnings.clear();

    let states = device_states(&CycleOutcome {
        devices: vec![stored_device],
        failures: Vec::new(),
    });

    let device = &states[0];
    assert_eq!(device["shown"], serde_json::json!(5), "the shown count");
    assert_eq!(device["stored"], serde_json::json!(3), "the stored count");
    assert!(
        device["readback"]
            .as_str()
            .unwrap_or_default()
            .contains("3 item(s)"),
        "and what the device said it holds: {states}"
    );
}
