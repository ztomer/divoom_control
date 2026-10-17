//! The feature table covers every model the daemon can name.

use super::*;
use crate::panel_model::{from_name, LARGER_THAN_16, NAME_PREFIXES};

#[test]
fn every_model_the_daemon_can_resolve_has_a_row() {
    for (prefix, model) in NAME_PREFIXES {
        assert!(
            of(model).is_some(),
            "{prefix} -> {model} has no features row"
        );
    }
    for (model, _) in LARGER_THAN_16 {
        assert!(of(model).is_some(), "{model} has no features row");
    }
}

#[test]
fn each_model_appears_once() {
    let mut names: Vec<&str> = FEATURES.iter().map(|(m, _, _)| *m).collect();
    let n = names.len();
    names.sort_unstable();
    names.dedup();
    assert_eq!(names.len(), n, "a model is listed twice");
    assert_eq!(n, 50, "the app's DeviceTypeEnum has 50 models");
}

#[test]
fn a_known_panel_reads_as_the_vendor_app_sets_it() {
    let tivoo_max = from_name(Some("Tivoo-Max-light"))
        .model
        .and_then(of)
        .expect("row");
    assert_eq!(tivoo_max["speaker"], true);
    assert_eq!(tivoo_max["sd_card"], true);
    assert_eq!(tivoo_max["wifi"], false);
    let pixoo64 = of("Pixoo64Wifi").expect("row");
    assert_eq!(pixoo64["wifi"], true);
    assert_eq!(pixoo64["speaker"], false);
    assert_eq!(
        of("PIXOO_MAX").expect("row")["clock_style"],
        "ClockNormal32"
    );
    assert!(of("NoSuchPanel").is_none());
}
