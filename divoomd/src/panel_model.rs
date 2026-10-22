//! What each panel IS: its model, its pixel resolution and its chassis (P3.1,
//! P3.4).
//!
//! Until this existed every client guessed size from the device name, each in
//! its own way: the web UI's `getDeviceDimensions` and the spatial stage's
//! `resolveDeviceSpec` disagreed with each other, and `divoom_lib`'s capability
//! table disagreed with both and with the vendor app (it called a Tivoo-Max
//! 32x32; the APK draws it at 16). The daemon owns the panel, so it owns this.
//!
//! The chassis came the same way (P3.4): the web UI kept a table of the
//! products' shapes and a second function that decided which shape a model
//! was, so the bench drew a panel from the GUI's idea of it while the daemon
//! said something else about the same panel. One table, here.
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
//! * model -> chassis: the products' published sizes, which no switch in the
//!   app states -- the family is a product line, not a protocol fact.

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

/// The chassis families: the name the web UI draws a panel by, and the
/// panel's published size in millimetres.
///
/// These were the web UI's table (`divoom_gui/web_ui/panel_facts.js`) until
/// P3.4 moved them here: a panel's shape is a fact about the panel, and a
/// table the GUI kept was a second place to look it up in. The millimetres
/// are the products' published sizes; the family is the product line.
pub const FAMILIES: &[(&str, f64, f64, f64)] = &[
    // family, width, height, the visible screen's edge
    ("panel", 120.0, 120.0, 100.0),
    ("ditoo", 90.0, 114.0, 64.0),
    ("timoo", 82.5, 90.0, 60.0),
    ("tivoo_max", 184.0, 163.0, 110.0),
    ("pixoo", 200.0, 200.0, 158.0),
    ("pixoo64", 261.0, 261.0, 210.0),
];

/// Which chassis family a model is, by the app's model name. A model that is
/// not listed is the generic family: the web UI's table said the same, and a
/// panel nobody can name is drawn as the generic one.
pub const FAMILY_OF: &[(&str, &str)] = &[
    ("DITOO", "ditoo"),
    ("DitooPlus", "ditoo"),
    ("DitooMic", "ditoo"),
    ("DitooPro", "ditoo"),
    ("DitooPro5", "ditoo"),
    ("DitooMic5", "ditoo"),
    ("TIMOO", "timoo"),
    ("TivooMax", "tivoo_max"),
    ("TivoomMax32", "tivoo_max"),
    ("Pixoo", "pixoo"),
    ("PIXOO_MAX", "pixoo"),
    ("Pixoo64Wifi", "pixoo64"),
    ("Pixoo64Wifi_2", "pixoo64"),
    ("Pixoo64Wifi_5G", "pixoo64"),
];

/// The chassis family of a model, or the generic one for a model the app
/// does not have (and for a panel with no name at all).
#[must_use]
pub fn family_of(model: Option<&str>) -> &'static str {
    model
        .and_then(|m| {
            FAMILY_OF
                .iter()
                .find(|(name, _)| *name == m)
                .map(|(_, f)| *f)
        })
        .unwrap_or("panel")
}

/// The panel's chassis: which family it is, and how big it is. Always
/// present: a panel nobody can name is the generic chassis, and the web UI
/// has no table to fall back on any more.
#[must_use]
pub fn chassis_of(model: Option<&str>) -> serde_json::Value {
    let family = family_of(model);
    let (_, w, h, screen) = FAMILIES
        .iter()
        .find(|(name, ..)| *name == family)
        .copied()
        .unwrap_or(FAMILIES[0]);
    serde_json::json!({
        "family": family,
        "w_mm": w,
        "h_mm": h,
        "screen_mm": screen,
    })
}

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
    /// The fields every device entry carries: what the panel is, how big,
    /// what shape it is, how that was decided, what the vendor app enables
    /// for that model, and the surfaces the app offers it (`null` when the
    /// model is not known -- never the baseline's guess).
    #[must_use]
    pub fn fields(&self) -> serde_json::Value {
        serde_json::json!({
            "model": self.model,
            "width": self.pixels,
            "height": self.pixels,
            "model_source": self.source,
            "chassis": chassis_of(self.model),
            "features": self.model.and_then(crate::panel_features::of),
            "screens": self.model.and_then(crate::panel_screens::screens_list_of),
        })
    }
}

#[cfg(test)]
#[path = "panel_model_tests.rs"]
mod tests;
