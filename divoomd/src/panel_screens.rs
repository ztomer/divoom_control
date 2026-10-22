//! What the vendor app OFFERS each panel model: the surfaces it can show
//! (P3.4).
//!
//! The app decides per model which screens its home carries, and it decides
//! it in one place: `DiscoverFunEnum`, which `setDeviceMode` sets for every
//! model, names a variant, and `DiscoverModel.s()` turns that variant into
//! the list of screens. The table below is that list, parsed out of the app's
//! own source by `tools/derive_panel_features.py` -- so it is the app's
//! statement about what a panel can show, and not a transcription.
//!
//! The FM radio is the clearest case: the app offers the radio screen to
//! exactly the Timebox and the Tiivoo 2, and to no other panel. The web UI
//! used to offer it to every panel whose NAME contained "tivoo" or "ditoo",
//! which is the opposite of the truth.

use crate::panel_features::FEATURES;

/// The home screens the app offers per `DiscoverFunEnum`: what a panel of
/// that kind can show.
///
/// One space-separated string per variant, not an array: `cargo fmt` wraps an
/// array of twenty strings over twenty lines, and this is data, not code.
pub const SCREENS: &[(&str, &str)] = &[
    ("TimeBoxDiscover", "fm_radio design animation voice chat alarm sleep time_planner game stopwatch celebrations scoreboard notification weather"),
    ("MiniDiscover", "design animation voice chat alarm sleep time_planner game stopwatch celebrations scoreboard notification weather"),
    ("TivooDiscover", "design animation light fill_game music mixer voice chat alarm sleep time_planner game stopwatch celebrations countdown noise scoreboard notification weather"),
    ("PixooAlarmMicDiscover", "design animation light fill_game music mixer voice chat alarm sleep time_planner game stopwatch celebrations countdown noise scoreboard notification weather"),
    ("PixooWifiDiscover", "design animation fill_game music chat alarm celebrations time_planner stopwatch countdown noise scoreboard"),
    ("PixooAlarmNoMicDiscover", "design animation light fill_game music mixer voice chat alarm sleep time_planner game stopwatch celebrations countdown scoreboard notification weather"),
    ("PlanetDiscover", "design animation music mixer alarm sleep power_on_off notification noise"),
    ("PixooNoAlarmNoMicDiscover", "design animation light fill_game music mixer voice chat game stopwatch countdown scoreboard notification weather"),
    ("DitooSoundConsole", "design animation light fill_game sound_control music mixer voice chat alarm sleep time_planner game stopwatch celebrations power_on_off countdown noise scoreboard notification weather"),
    ("KaraokeDiscover", "design animation fill_game chat music mixer"),
    ("DitooProConsole", "design animation light fill_game music mixer voice chat alarm sleep time_planner game stopwatch celebrations power_on_off countdown noise scoreboard notification weather"),
    ("Lcd5WifiDiscover", "design ai fill_game music chat alarm celebrations stopwatch countdown noise scoreboard"),
    ("TivooLcdDiscover", "design ai tomato photo_add_device lyric fm_radio alarm music white_noise power_on_off game fill_game stopwatch time_planner mixer voice celebrations countdown noise scoreboard notification weather chat"),
    ("Bag64Discover", "design animation fill_game music mixer chat game stopwatch countdown scoreboard notification weather"),
    ("PhotoFrameDiscover", "album design ai danmaku tomato google_calendars outlook_calendars power_on_off time_planner scoreboard alarm fill_game stopwatch countdown noise chat"),
    ("ESportDiscover", ""),
    ("TimeBoxEvoDiscover", "design animation light fill_game music mixer voice chat alarm sleep power_on_off time_planner game stopwatch celebrations countdown noise scoreboard notification weather"),
    ("MiniTooDiscover", "design ai tomato photo_add_device lyric alarm music white_noise power_on_off game fill_game stopwatch time_planner mixer voice celebrations countdown noise scoreboard notification weather chat"),
    ("DigitalBadgeDiscover", "album design ai danmaku fill_game power_on_off stopwatch countdown noise scoreboard notification weather chat"),
    ("DivoomFlowToo", "aid_sleep design ai alarm tomato stopwatch countdown scoreboard voice power_on_off noise fill_game mixer music weather"),
];

/// The screens the app offers for an APK model name, or `None` for a name the
/// app does not have. The list is the app's, so a model with no home list of
/// its own (the app has no branch for `ESportDiscover`) gets an empty one
/// rather than a guess.
#[must_use]
pub fn screens_of(model: &str) -> Option<&'static str> {
    let (_, _, _, discover, _) = FEATURES.iter().find(|(m, ..)| *m == model)?;
    SCREENS
        .iter()
        .find(|(name, _)| *name == *discover)
        .map(|(_, screens)| *screens)
}

/// The screens as a list, for the wire.
#[must_use]
pub fn screens_list_of(model: &str) -> Option<Vec<&'static str>> {
    screens_of(model).map(|s| s.split_whitespace().collect())
}
