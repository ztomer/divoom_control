//! What the vendor app enables for each panel model (P4.1).
//!
//! The rows are the output of `tools/derive_panel_features.py`, which RUNS
//! the decompiled app's `DeviceTypeEnum.setDeviceMode` for every model and
//! reads back the switches it leaves set; `tests/test_panel_features_parity.py`
//! re-runs it and compares whenever the decompiled sources are on the machine.
//! It is not hand-transcribed: that is how `divoom_lib`'s capability table
//! came to hold 18 wrong resolutions.
//!
//! Only switches whose consumers in the app were read, and mean their name:
//!
//! * `speaker` -- `MusicEnum`: the Bluetooth-audio pairing prompt, the Voice
//!   screen, the audio rows of the Bluetooth settings.
//! * `sd_card` -- `SdEnum`: the SD card as a music source; SD firmware update.
//! * `temp_sensor` -- `TempSensorEnum`: the indoor reading on the weather
//!   screens.
//! * `wifi` -- `WifiBlueArchEnum::WifiArchMode`: driven over Wi-Fi (MQTT).
//! * `clock_style` -- `ClockModeEnum`: which family of clock faces the app
//!   offers.
//!
//! There is no FM-radio flag, on purpose: the app's `FmModeEnum` only decides
//! whether FM may be an alarm or sleep sound, and the FM screen is not
//! decided per model at all. A "radio" flag built from it would be wrong for
//! every panel that has one.

use serde_json::{json, Value};

/// No switch on.
pub const NONE: u8 = 0;
/// `MusicEnum::SupportMusic`.
pub const SPEAKER: u8 = 1;
/// `SdEnum::SupportSd`.
pub const SD_CARD: u8 = 1 << 1;
/// `TempSensorEnum::TempSensor`.
pub const TEMP_SENSOR: u8 = 1 << 2;
/// `WifiBlueArchEnum::WifiArchMode`.
pub const WIFI: u8 = 1 << 3;

/// Every `DeviceTypeEnum` model, in the app's order: (model, switches,
/// `ClockModeEnum`).
pub const FEATURES: &[(&str, u8, &str)] = &[
    ("TIMEBOX_NORMAL", SPEAKER, "ClockNormal16"),
    ("TIMEBOX_MIN", SPEAKER, "ClockNormal16"),
    ("Tivoo", SPEAKER | SD_CARD, "ClockNormal16"),
    ("TimeboxEvo", SPEAKER, "ClockNormal16"),
    ("Pixoo", NONE, "ClockNormal16"),
    ("TivooMax", SPEAKER | SD_CARD, "ClockNormal16"),
    ("Pixoo64Wifi", WIFI, "ClockNormal16"),
    ("TIMOO", SPEAKER | SD_CARD, "ClockNormal16"),
    ("DITOO", SPEAKER | SD_CARD, "ClockNormal16"),
    ("Pixel_Factory", NONE, "ClockNormal16"),
    ("Planet9", NONE, "ClockNormal16"),
    ("PixelBag", NONE, "ClockNormal16"),
    ("PIXOO_MAX", NONE, "ClockNormal32"),
    ("PIXOO_VJ", NONE, "ClockNormal16"),
    ("Pixoo_SlingBag", NONE, "ClockNormal16"),
    ("DitooPlus", SPEAKER | SD_CARD, "ClockNormal16"),
    ("TivooLit", SPEAKER | SD_CARD, "ClockNormal16"),
    ("PixelBagM", NONE, "ClockNormal16"),
    ("PixelBagS", NONE, "ClockNormal16"),
    ("PixoolNull", TEMP_SENSOR, "ClockNormal16"),
    ("PixelBagNew", NONE, "ClockNormal16"),
    ("Zooe", SPEAKER | SD_CARD, "ClockNormal16"),
    ("TivoomMax32", SPEAKER, "ClockNormal32"),
    ("DitooMic", SPEAKER | SD_CARD, "ClockDitooMic"),
    ("Karaoke", SPEAKER, "ClockKaraoke"),
    ("Pixoo16Wifi", WIFI, "ClockNormal16"),
    ("DitooPro", SPEAKER | SD_CARD, "ClockDitooMic"),
    ("Lcd5Wifi", WIFI, "ClockNormal16"),
    ("PixelBagBIPI", TEMP_SENSOR, "ClockNormal16"),
    ("Pixoo64Wifi_2", WIFI, "ClockNormal16"),
    ("TivooLcd", SPEAKER | SD_CARD, "ClockNormal16"),
    ("CyberBag", NONE, "ClockNormal32"),
    ("Dipow35", NONE, "ClockNormal32"),
    ("Dipow65", NONE, "ClockNormal32"),
    ("DitooPro5", SPEAKER | SD_CARD, "ClockDitooMic"),
    ("DitooMic5", SPEAKER | SD_CARD, "ClockDitooMic"),
    ("PhotoFrameWifi", SPEAKER | WIFI, "ClockNormal16"),
    ("CyberBag2", NONE, "ClockNormal32"),
    ("ESport", SPEAKER, "ClockNormal16"),
    ("Dipow67", NONE, "ClockNormal32"),
    ("TimeBoxEvoPro", SPEAKER, "ClockDitooMic"),
    ("MiniToo", SPEAKER | SD_CARD, "ClockNormal16"),
    ("PhotoSpeakerWifi", SPEAKER | WIFI, "ClockNormal16"),
    ("DigitalBadge", NONE, "ClockNormal16"),
    ("PhotoFrameWifiPure", SPEAKER | WIFI, "ClockNormal16"),
    ("Pixoo64Wifi_5G", WIFI, "ClockNormal16"),
    ("Lcd5Wifi_5G", WIFI, "ClockNormal16"),
    ("DivoomFlowToo", SPEAKER | SD_CARD, "ClockNormal16"),
    ("Dipow40", NONE, "ClockNormal32"),
    ("Dipow65_2", NONE, "ClockNormal32"),
];

/// The feature switches for an APK model name, or `None` for a name the app
/// does not have.
#[must_use]
pub fn of(model: &str) -> Option<Value> {
    FEATURES
        .iter()
        .find(|(m, _, _)| *m == model)
        .map(|&(_, on, clock)| {
            json!({
                "speaker": on & SPEAKER != 0,
                "sd_card": on & SD_CARD != 0,
                "temp_sensor": on & TEMP_SENSOR != 0,
                "wifi": on & WIFI != 0,
                "clock_style": clock,
                "source": "vendor app setDeviceMode",
            })
        })
}

#[cfg(test)]
#[path = "panel_features_tests.rs"]
mod tests;
