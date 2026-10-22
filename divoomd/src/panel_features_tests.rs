//! The feature table covers every model the daemon can name.

use super::*;
use crate::panel_model::{from_name, LARGER_THAN_16, NAME_PREFIXES};
use crate::panel_screens::{screens_list_of, screens_of, SCREENS};

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
    let mut names: Vec<&str> = FEATURES.iter().map(|(m, ..)| *m).collect();
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

/// The radio is the switch the old table said it could not carry (P3.4).
///
/// It is the app's own per-model statement twice over: the FM home screen is
/// offered to exactly `TimeBoxDiscover` and `TivooLcdDiscover`, and the FM
/// entry survives in the alarm and sleep sound lists for exactly those two
/// models. The old table said a radio flag built from `FmModeEnum` "would be
/// wrong for every Ditoo/Tivoo/Timoo" -- the app offers those models no FM
/// screen at all, which is the same fact the other way round.
#[test]
fn the_radio_is_the_timebox_and_the_tiivoo_two() {
    for model in ["TIMEBOX_NORMAL", "TivooLcd"] {
        assert_eq!(of(model).expect("row")["radio"], true, "{model}");
    }
    for model in ["DITOO", "TIMOO", "TivooMax", "TivooLit", "Pixoo"] {
        assert_eq!(of(model).expect("row")["radio"], false, "{model}");
    }
}

/// The VJ channel belongs to the app's common light screen, which the mini
/// Timebox and the 64x64 picture frame do not get.
#[test]
fn the_vj_channel_is_the_common_light_screen() {
    assert_eq!(of("DITOO").expect("row")["vj"], true);
    assert_eq!(of("TIMOO").expect("row")["vj"], true);
    assert_eq!(of("TIMEBOX_MIN").expect("row")["vj"], false);
    assert_eq!(of("Pixoo64Wifi").expect("row")["vj"], false);
    // A karaoke panel gets the common light screen but no light screen of
    // its own, so there is no VJ channel to reach.
    assert_eq!(of("Karaoke").expect("row")["vj"], false);
}

/// The screens are the app's home list: what the panel can show.
#[test]
fn the_screens_are_the_apps_own_home_list() {
    let tivoo = screens_list_of("TivooMax").expect("row");
    assert!(tivoo.contains(&"weather"), "{tivoo:?}");
    assert!(tivoo.contains(&"alarm"), "{tivoo:?}");
    assert!(tivoo.contains(&"light"), "{tivoo:?}");
    assert!(!tivoo.contains(&"fm_radio"), "{tivoo:?}");
    let timebox = screens_list_of("TIMEBOX_NORMAL").expect("row");
    assert!(timebox.contains(&"fm_radio"), "{timebox:?}");
    assert!(!timebox.contains(&"light"), "{timebox:?}");
    // The app has no home list of its own for the ESport, and nothing is
    // invented for it.
    assert_eq!(screens_list_of("ESport").expect("row"), Vec::<&str>::new());
    assert!(screens_of("NoSuchPanel").is_none());
}

/// Every model in the table names a home list the screens table knows.
#[test]
fn every_model_names_a_home_list_the_screens_table_knows() {
    for (model, _, _, discover, _) in FEATURES {
        assert!(
            SCREENS.iter().any(|(name, _)| name == discover),
            "{model} names the home list {discover}, which the screens table does not have"
        );
    }
}
