//! What the vendor app enables for each panel model (P4.1, P3.4).
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
//! * `radio` -- `FmModeEnum::SupportFm`: the panel has an FM radio. The app
//!   offers the FM home screen to EXACTLY the models whose switch is on
//!   (`TimeBoxDiscover` and `TivooLcdDiscover`), and keeps the FM entry in
//!   the alarm and sleep sound lists only for them. Two independent per-model
//!   statements agree, so this is the vendor's statement about the radio --
//!   NOT a guess from the sound list, which is what the table used to say.
//! * `mic` -- `MicEnum::SupportMic`: the panel has the microphone; the app
//!   pairs the switch with its `...MicDiscover` home variants.
//! * `vj` -- the panel gets the app's COMMON light screen
//!   (`LightCommonMainFragment`), whose config list offers the VJ channel
//!   (`LightConfigFragment`). The mini Timebox and the 64x64 picture frame
//!   get other screens and no VJ.
//! * `clock_style` -- `ClockModeEnum`: which family of clock faces the app
//!   offers.
//!
//! `SCREENS` is the app's own home list per `DiscoverFunEnum`: the surfaces
//! it offers for a model ("what it can show"). It is parsed out of
//! `DiscoverModel.s()` by the same tool, so it is the app's statement and not
//! a transcription.

use serde_json::{json, Value};

/// No switch on.
pub const NONE: u32 = 0;
/// `MusicEnum::SupportMusic`.
pub const SPEAKER: u32 = 1;
/// `SdEnum::SupportSd`.
pub const SD_CARD: u32 = 1 << 1;
/// `TempSensorEnum::TempSensor`.
pub const TEMP_SENSOR: u32 = 1 << 2;
/// `WifiBlueArchEnum::WifiArchMode`.
pub const WIFI: u32 = 1 << 3;
/// `FmModeEnum::SupportFm`.
pub const RADIO: u32 = 1 << 4;
/// `MicEnum::SupportMic`.
pub const MIC: u32 = 1 << 5;
/// The app's common light screen, and with it the VJ channel.
pub const VJ: u32 = 1 << 6;

/// Every `DeviceTypeEnum` model, in the app's order: (model, switches,
/// `ClockModeEnum`, `DiscoverFunEnum`, `UiArchEnum`).
pub const FEATURES: &[(&str, u32, &str, &str, &str)] = &[
    (
        "TIMEBOX_NORMAL",
        SPEAKER | RADIO | MIC,
        "ClockNormal16",
        "TimeBoxDiscover",
        "MiniUiArch",
    ),
    (
        "TIMEBOX_MIN",
        SPEAKER | MIC,
        "ClockNormal16",
        "MiniDiscover",
        "MiniUiArch",
    ),
    (
        "Tivoo",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "TimeboxEvo",
        SPEAKER | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "Pixoo",
        MIC | VJ,
        "ClockNormal16",
        "PixooAlarmMicDiscover",
        "PixooArch",
    ),
    (
        "TivooMax",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "Pixoo64Wifi",
        WIFI | MIC,
        "ClockNormal16",
        "PixooWifiDiscover",
        "Pixoo64Arch",
    ),
    (
        "TIMOO",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "DITOO",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "Pixel_Factory",
        VJ,
        "ClockNormal16",
        "PixooAlarmNoMicDiscover",
        "PixooArch",
    ),
    (
        "Planet9",
        MIC,
        "ClockNormal16",
        "PlanetDiscover",
        "PlanetArch",
    ),
    (
        "PixelBag",
        VJ,
        "ClockNormal16",
        "PixooNoAlarmNoMicDiscover",
        "PixooArch",
    ),
    (
        "PIXOO_MAX",
        MIC | VJ,
        "ClockNormal32",
        "PixooAlarmMicDiscover",
        "PixooArch",
    ),
    (
        "PIXOO_VJ",
        MIC | VJ,
        "ClockNormal16",
        "PixooAlarmMicDiscover",
        "PixooArch",
    ),
    (
        "Pixoo_SlingBag",
        VJ,
        "ClockNormal16",
        "PixooNoAlarmNoMicDiscover",
        "PixooArch",
    ),
    (
        "DitooPlus",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "TivooLit",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "PixelBagM",
        VJ,
        "ClockNormal16",
        "PixooNoAlarmNoMicDiscover",
        "PixooArch",
    ),
    (
        "PixelBagS",
        VJ,
        "ClockNormal16",
        "PixooNoAlarmNoMicDiscover",
        "PixooArch",
    ),
    (
        "PixoolNull",
        TEMP_SENSOR | MIC,
        "ClockNormal16",
        "TivooDiscover",
        "MiniUiArch",
    ),
    (
        "PixelBagNew",
        VJ,
        "ClockNormal16",
        "PixooNoAlarmNoMicDiscover",
        "PixooArch",
    ),
    (
        "Zooe",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockNormal16",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "TivoomMax32",
        SPEAKER | MIC | VJ,
        "ClockNormal32",
        "TivooDiscover",
        "TiViUiArch",
    ),
    (
        "DitooMic",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockDitooMic",
        "DitooSoundConsole",
        "TiViUiArch",
    ),
    (
        "Karaoke",
        SPEAKER,
        "ClockKaraoke",
        "KaraokeDiscover",
        "PixooArch",
    ),
    (
        "Pixoo16Wifi",
        WIFI | MIC,
        "ClockNormal16",
        "PixooWifiDiscover",
        "Pixoo64Arch",
    ),
    (
        "DitooPro",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockDitooMic",
        "DitooProConsole",
        "TiViUiArch",
    ),
    (
        "Lcd5Wifi",
        WIFI | MIC,
        "ClockNormal16",
        "Lcd5WifiDiscover",
        "Lcd5WifiArch",
    ),
    (
        "PixelBagBIPI",
        TEMP_SENSOR | MIC,
        "ClockNormal16",
        "TivooDiscover",
        "MiniUiArch",
    ),
    (
        "Pixoo64Wifi_2",
        WIFI | MIC,
        "ClockNormal16",
        "PixooWifiDiscover",
        "Pixoo64Arch",
    ),
    (
        "TivooLcd",
        SPEAKER | SD_CARD | RADIO | MIC,
        "ClockNormal16",
        "TivooLcdDiscover",
        "BlueHighPixelArch",
    ),
    (
        "CyberBag",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "PixooArch",
    ),
    (
        "Dipow35",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "ChargerPixelArch",
    ),
    (
        "Dipow65",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "ChargerPixelArch",
    ),
    (
        "DitooPro5",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockDitooMic",
        "DitooProConsole",
        "TiViUiArch",
    ),
    (
        "DitooMic5",
        SPEAKER | SD_CARD | MIC | VJ,
        "ClockDitooMic",
        "DitooSoundConsole",
        "TiViUiArch",
    ),
    (
        "PhotoFrameWifi",
        SPEAKER | WIFI | MIC,
        "ClockNormal16",
        "PhotoFrameDiscover",
        "Pixoo64Arch",
    ),
    (
        "CyberBag2",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "PixooArch",
    ),
    (
        "ESport",
        SPEAKER,
        "ClockNormal16",
        "ESportDiscover",
        "ESportArch",
    ),
    (
        "Dipow67",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "ChargerPixelArch",
    ),
    (
        "TimeBoxEvoPro",
        SPEAKER | MIC | VJ,
        "ClockDitooMic",
        "TimeBoxEvoDiscover",
        "TiViUiArch",
    ),
    (
        "MiniToo",
        SPEAKER | SD_CARD | MIC,
        "ClockNormal16",
        "MiniTooDiscover",
        "BlueHighPixelArch",
    ),
    (
        "PhotoSpeakerWifi",
        SPEAKER | WIFI | MIC,
        "ClockNormal16",
        "PhotoFrameDiscover",
        "Pixoo64Arch",
    ),
    (
        "DigitalBadge",
        MIC,
        "ClockNormal16",
        "DigitalBadgeDiscover",
        "BlueHighPixelArch",
    ),
    (
        "PhotoFrameWifiPure",
        SPEAKER | WIFI | MIC,
        "ClockNormal16",
        "PhotoFrameDiscover",
        "Pixoo64Arch",
    ),
    (
        "Pixoo64Wifi_5G",
        WIFI | MIC,
        "ClockNormal16",
        "PixooWifiDiscover",
        "Pixoo64Arch",
    ),
    (
        "Lcd5Wifi_5G",
        WIFI | MIC,
        "ClockNormal16",
        "Lcd5WifiDiscover",
        "Lcd5WifiArch",
    ),
    (
        "DivoomFlowToo",
        SPEAKER | SD_CARD | MIC,
        "ClockNormal16",
        "DivoomFlowToo",
        "BlueHighPixelArch",
    ),
    (
        "Dipow40",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "ChargerPixelArch",
    ),
    (
        "Dipow65_2",
        NONE,
        "ClockNormal32",
        "Bag64Discover",
        "ChargerPixelArch",
    ),
];

/// The feature switches for an APK model name, or `None` for a name the app
/// does not have.
#[must_use]
pub fn of(model: &str) -> Option<Value> {
    FEATURES
        .iter()
        .find(|(m, ..)| *m == model)
        .map(|&(_, on, clock, _, arch)| {
            json!({
                "speaker": on & SPEAKER != 0,
                "sd_card": on & SD_CARD != 0,
                "temp_sensor": on & TEMP_SENSOR != 0,
                "wifi": on & WIFI != 0,
                "radio": on & RADIO != 0,
                "mic": on & MIC != 0,
                "vj": on & VJ != 0,
                "clock_style": clock,
                "ui": arch,
                "source": "vendor app setDeviceMode",
            })
        })
}

#[cfg(test)]
#[path = "panel_features_tests.rs"]
mod tests;
