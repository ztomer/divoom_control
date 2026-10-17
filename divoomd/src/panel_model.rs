//! What each panel IS: its model and its pixel resolution (P3.1).
//!
//! Until this existed every client guessed size from the device name, each in
//! its own way: the web UI's `getDeviceDimensions` and the spatial stage's
//! `resolveDeviceSpec` disagreed with each other, and `divoom_lib`'s capability
//! table disagreed with both and with the vendor app (it called a Tivoo-Max
//! 32x32; the APK draws it at 16). The daemon owns the panel, so it owns this.
//!
//! Ground truth is the decompiled vendor app, not memory:
//!
//! * name -> model: `DeviceFunction.DeviceTypeEnum.setDeviceModel(String)`
//!   (`references/apk/decompiled_src/sources/com/divoom/Divoom/utils/
//!   DeviceFunction/DeviceFunction.java`), a FIRST-MATCH `startsWith` chain, so
//!   [`NAME_PREFIXES`] keeps its order exactly. One addition, cited where it
//!   is made: `Pixoo64`.
//! * model -> pixels: the same file's `setDeviceMode(DeviceTypeEnum)`, which
//!   starts every model at `DevicePixel16` and raises it per model branch.

/// BLE advertised-name prefix -> APK `DeviceTypeEnum` name, first match wins.
pub const NAME_PREFIXES: &[(&str, &str)] = &[
    ("Tivoo-Max32", "TivoomMax32"),
    ("Timebox-Evo", "TimeBoxEvoPro"),
    ("Tivoo-Max", "TivooMax"),
    ("Divoom Tiivoo 2", "TivooLcd"),
    ("Divoom MiniToo", "MiniToo"),
    ("Divoom FlowToo", "DivoomFlowToo"),
    ("Divoom Emodo", "DigitalBadge"),
    ("Tivoo-Lit", "TivooLit"),
    ("Ditoo-Plus", "DitooPlus"),
    ("DitooMic", "DitooMic"),
    ("DitooPro", "DitooPro"),
    ("Divoom Ditoo-5M", "DitooMic5"),
    ("Divoom Ditoo-5Pro", "DitooPro5"),
    ("Tivoo", "Tivoo"),
    ("StarSpark", "Karaoke"),
    ("Karaoke", "Karaoke"),
    ("Cyberbag", "CyberBag2"),
    ("CyberBag", "CyberBag"),
    ("DiPow-35", "Dipow35"),
    ("DiPow-40", "Dipow40"),
    ("DiPow-65", "Dipow65"),
    ("Dipow-65", "Dipow65_2"),
    ("DiPow-67", "Dipow67"),
    ("Pixoo-SlingBag", "Pixoo_SlingBag"),
    ("Divoom & BIPI", "Pixoo_SlingBag"),
    ("Pixoo-Backpack", "PixelBag"),
    ("Pixel-Bag", "PixelBag"),
    ("Divoom-Backpack-M", "PixelBagM"),
    // The APK tests "Divoom-Backpack" BEFORE "Divoom-Backpack-S", so the
    // second can never match there either; kept in order, unreachable, rather
    // than "fixed" into a behaviour the vendor app does not have.
    ("Divoom-Backpack", "PixelBagNew"),
    ("Divoom-Backpack-S", "PixelBagS"),
    ("Pixel-Factory", "Pixel_Factory"),
    ("Pixoo-Max", "PIXOO_MAX"),
    ("Pixoo-VJ", "PIXOO_VJ"),
    // NOT in `setDeviceModel`: the APK learns a Pixoo 64 through its Wi-Fi
    // setup (`WifiConnectSuccessFragment` sets `Pixoo64Wifi`), never from a
    // BLE name. `Pixoo64` is a name the app knows (`Constant.f10692g`), and
    // without this line it would fall to the 16x16 `Pixoo` below.
    ("Pixoo64", "Pixoo64Wifi"),
    ("Pixoo", "Pixoo"),
    ("TimeBox-Evo", "TimeboxEvo"),
    ("TimeBox-mini", "TIMEBOX_MIN"),
    ("Timoo", "TIMOO"),
    ("Zooe", "Zooe"),
    ("Ditoo", "DITOO"),
    ("Planet", "Planet9"),
    ("Divoom D-base", "ESport"),
];

/// Every model `setDeviceMode` raises above the 16x16 default.
pub const LARGER_THAN_16: &[(&str, u32)] = &[
    ("PIXOO_MAX", 32),
    ("TivoomMax32", 32),
    ("Pixoo64Wifi", 64),
    ("Pixoo64Wifi_2", 64),
    ("Pixoo64Wifi_5G", 64),
    ("CyberBag", 64),
    ("CyberBag2", 64),
    ("Karaoke", 64),
    ("Dipow35", 64),
    ("Dipow40", 64),
    ("Dipow65", 64),
    ("Dipow65_2", 64),
    ("Dipow67", 64),
    ("TivooLcd", 128),
    ("MiniToo", 128),
    ("DivoomFlowToo", 128),
    ("Lcd5Wifi", 128),
    ("Lcd5Wifi_5G", 128),
    ("DigitalBadge", 256),
    ("PhotoFrameWifi", 256),
    ("PhotoSpeakerWifi", 256),
    ("PhotoFrameWifiPure", 256),
];

/// `setDeviceMode`'s starting point for every model.
pub const DEFAULT_PIXELS: u32 = 16;

/// What the daemon knows about one panel, and how it knows it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Panel {
    /// The APK `DeviceTypeEnum` name; `None` when the name matched nothing.
    pub model: Option<&'static str>,
    /// Square panel edge in pixels; `None` when there is nothing to go on.
    pub pixels: Option<u32>,
    /// `"name"` (matched an advertised name), `"default"` (a name that
    /// matched nothing: the APK's 16x16 starting point, not a fact about this
    /// panel), or `"unknown"` (no name at all, e.g. a LAN panel).
    pub source: &'static str,
}

/// The pixel edge for an APK model name.
#[must_use]
pub fn pixels_of(model: &str) -> u32 {
    LARGER_THAN_16
        .iter()
        .find(|(m, _)| *m == model)
        .map_or(DEFAULT_PIXELS, |(_, px)| *px)
}

/// Resolve a panel from its advertised name, if it has one.
#[must_use]
pub fn from_name(name: Option<&str>) -> Panel {
    let Some(name) = name.filter(|n| !n.is_empty()) else {
        return Panel {
            model: None,
            pixels: None,
            source: "unknown",
        };
    };
    NAME_PREFIXES
        .iter()
        .find(|(prefix, _)| name.starts_with(prefix))
        .map_or(
            Panel {
                model: None,
                pixels: Some(DEFAULT_PIXELS),
                source: "default",
            },
            |(_, model)| Panel {
                model: Some(model),
                pixels: Some(pixels_of(model)),
                source: "name",
            },
        )
}

impl Panel {
    /// The fields every device entry carries.
    #[must_use]
    pub fn fields(&self) -> serde_json::Value {
        serde_json::json!({
            "model": self.model,
            "width": self.pixels,
            "height": self.pixels,
            "model_source": self.source,
        })
    }
}

#[cfg(test)]
#[path = "panel_model_tests.rs"]
mod tests;
