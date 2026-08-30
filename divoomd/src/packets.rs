//! Typed 0x45 channel packets — ONE construction site per wire format.
//!
//! # Why this module exists (R67, class C1)
//!
//! The 0x45 packet family had **four** independent builders: three Rust
//! `device_call` arms plus the Python one in `divoom_lib/display/__init__.py`.
//! They disagreed, and every disagreement was a shipped bug:
//!
//! | builder                          | byte 4   | byte 5  | byte 6   | parameterized |
//! |----------------------------------|----------|---------|----------|---------------|
//! | Python (canonical, from APK C2()) | humidity | weather | date     | all           |
//! | `display.set_clock_rich`          | humidity | weather | date     | all           |
//! | `display.show_clock`              | weather  | temp    | calendar | all           |
//! | `device.show_clock`               | 0        | 0       | 0        | style only    |
//!
//! So asking `display.show_clock` for the weather overlay turned on **humidity**
//! on the device, `humidity=` was ignored entirely (the arm did not even accept
//! that kwarg name), and the wall's `device.show_clock` silently discarded the
//! user's colour. The lighting packet had the same shape: `display.show_light`
//! hardcoded the lighting-type byte to `0x00`, so all five ambient modes sent
//! identical Plain-Colour packets while every RPC returned success.
//!
//! The fix is structural, not per-field: a struct with **named** fields that
//! serializes in exactly one place. A caller cannot put weather in the humidity
//! slot because it does not choose slots, and a dropped parameter is a missing
//! struct field — a compile error — rather than a silent `0x00`.
//!
//! Canonical layouts are pinned by `divoom_lib/display/__init__.py`, which in
//! turn cites the Divoom APK's `C2()`. Do not reorder without a wire trace.

/// The `set light mode` command id every channel packet below is sent under.
pub const CMD_SET_LIGHT_MODE: u8 = 0x45;

/// Channel selector — byte 0 of a 0x45 packet.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Channel {
    Clock = 0x00,
    Lighting = 0x01,
    Cloud = 0x02,
    Vj = 0x03,
    Visualization = 0x04,
    Design = 0x05,
    Scoreboard = 0x06,
}

/// Ambient lighting effect — byte 5 of a lighting packet.
///
/// Values match `divoom_lib/models/constants_scheduling.py` (which took them
/// from `node-divoom-timebox-evo/src/types.ts`). `Plain` is the only mode that
/// honours the colour; the rest use fixed device palettes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum LightingType {
    PlainColor = 0,
    Love = 1,
    Plants = 2,
    Sleeping = 3,
    NoMosquito = 4,
}

impl LightingType {
    /// Map a wire/RPC integer to a mode. Out-of-range falls back to `PlainColor`
    /// — the device ignores unknown types, and guessing a different effect would
    /// be worse than the documented default.
    pub fn from_i64(v: i64) -> Self {
        match v {
            1 => Self::Love,
            2 => Self::Plants,
            3 => Self::Sleeping,
            4 => Self::NoMosquito,
            _ => Self::PlainColor,
        }
    }
}

/// The clock channel packet.
///
/// Wire: `[env, twentyfour, style, active, humidity, weather, date, R, G, B]`
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockPacket {
    /// Environment/clock selector; 0 selects the clock channel.
    pub env: u8,
    pub twentyfour: bool,
    /// Clock face style, 0-15.
    pub style: u8,
    pub active: bool,
    pub humidity: bool,
    pub weather: bool,
    pub date: bool,
    pub rgb: [u8; 3],
}

impl Default for ClockPacket {
    fn default() -> Self {
        Self {
            env: 0,
            twentyfour: true,
            style: 0,
            active: true,
            humidity: false,
            weather: false,
            date: false,
            rgb: [0xFF, 0xFF, 0xFF],
        }
    }
}

impl ClockPacket {
    /// The ONLY place a clock packet becomes bytes.
    pub fn to_bytes(self) -> [u8; 10] {
        [
            self.env,
            self.twentyfour as u8,
            self.style.min(15),
            self.active as u8,
            self.humidity as u8,
            self.weather as u8,
            self.date as u8,
            self.rgb[0],
            self.rgb[1],
            self.rgb[2],
        ]
    }
}

/// The lighting (ambient) channel packet.
///
/// Wire: `[channel, R, G, B, brightness, lighting_type, power, 0, 0, 0]`
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LightPacket {
    pub rgb: [u8; 3],
    /// 0-100.
    pub brightness: u8,
    pub kind: LightingType,
    pub power: bool,
}

impl Default for LightPacket {
    fn default() -> Self {
        Self {
            rgb: [0xFF, 0xFF, 0xFF],
            brightness: 100,
            kind: LightingType::PlainColor,
            power: true,
        }
    }
}

impl LightPacket {
    /// The ONLY place a lighting packet becomes bytes.
    pub fn to_bytes(self) -> [u8; 10] {
        [
            Channel::Lighting as u8,
            self.rgb[0],
            self.rgb[1],
            self.rgb[2],
            self.brightness.min(100),
            self.kind as u8,
            self.power as u8,
            0,
            0,
            0,
        ]
    }
}

/// The `set temp/weather` command id (0x5F).
pub const CMD_SET_TEMP_WEATHER: u8 = 0x5F;

/// Divoom weather icons, as the device numbers them.
///
/// Values match `divoom_lib/models` and the WMO mapping in
/// `divoom_lib/weather_provider.py`. Both languages agree on all 48 WMO codes
/// (verified 2026-08-29); this enum is the Rust side of that agreement.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum WeatherType {
    Clear = 1,
    CloudySky = 3,
    Thunderstorm = 5,
    Rain = 6,
    Snow = 8,
    Fog = 9,
}

impl WeatherType {
    /// Map a wire/RPC integer to an icon, defaulting to `Clear`.
    ///
    /// Clear is the neutral icon: an unknown code should show something
    /// innocuous rather than, say, a thunderstorm.
    pub fn from_i64(v: i64) -> Self {
        match v {
            3 => Self::CloudySky,
            5 => Self::Thunderstorm,
            6 => Self::Rain,
            8 => Self::Snow,
            9 => Self::Fog,
            _ => Self::Clear,
        }
    }
}

/// Encode a Celsius temperature as the device's single signed byte.
///
/// Negative temperatures are two's complement: -1 becomes 255, -127 becomes
/// 129. Mirrors `Weather._encode_temperature` in
/// `divoom_lib/system/weather.py`, which is the APK-verified form.
///
/// This exists as a named function because "cast it to u8" is exactly the kind
/// of step that looks obviously right and is silently wrong for half its input
/// range — the negative half, which nobody tests in July.
pub fn encode_temperature(celsius: i8) -> u8 {
    celsius as u8
}

/// The temperature + weather-icon packet.
///
/// Wire: `[encoded_temperature, weather_type]` under command 0x5F.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WeatherPacket {
    pub temperature_c: i8,
    pub weather: WeatherType,
}

impl WeatherPacket {
    /// The ONLY place a weather packet becomes bytes.
    pub fn to_bytes(self) -> [u8; 2] {
        [encode_temperature(self.temperature_c), self.weather as u8]
    }
}

/// Parse `#RRGGBB` (or `RRGGBB`) into bytes.
///
/// R67: this existed in THREE copies — display.rs, text.rs and sleep.rs. A
/// helper duplicated per file is one that eventually differs per file, which is
/// the same class as the packet builders this module exists to unify.
pub fn parse_hex_color(s: &str) -> Option<[u8; 3]> {
    let s = s.trim().trim_start_matches('#');
    if s.len() != 6 {
        return None;
    }
    Some([
        u8::from_str_radix(&s[0..2], 16).ok()?,
        u8::from_str_radix(&s[2..4], 16).ok()?,
        u8::from_str_radix(&s[4..6], 16).ok()?,
    ])
}

/// A bare channel-switch packet: `[channel, 0 x 9]`.
///
/// The device needs the full 10 bytes to switch reliably; a short packet is
/// silently ignored (see the padding notes in `divoom_lib/display/__init__.py`).
pub fn channel_switch(channel: Channel) -> [u8; 10] {
    [channel as u8, 0, 0, 0, 0, 0, 0, 0, 0, 0]
}

/// A VJ-effect packet: `[Vj, number + 1, 0 x 8]`. VJ effects are 1-indexed on
/// BLE hardware, so the caller passes the 0-indexed number the UI shows.
pub fn vj_effect(number: u8) -> [u8; 10] {
    [
        Channel::Vj as u8,
        number.saturating_add(1),
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
}

/// A visualizer packet: `[Visualization, number, 0 x 8]`.
pub fn visualization(number: u8) -> [u8; 10] {
    [Channel::Visualization as u8, number, 0, 0, 0, 0, 0, 0, 0, 0]
}
