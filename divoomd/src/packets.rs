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

#[cfg(test)]
mod tests {
    use super::*;

    // ── Clock: every overlay owns its own slot ───────────────────────────
    // These are the tests that would have caught C1. Each asserts ONE overlay
    // at a time, because a swapped pair is invisible when they are set together.

    #[test]
    fn clock_humidity_sets_byte_4_only() {
        let p = ClockPacket {
            humidity: true,
            ..Default::default()
        };
        let b = p.to_bytes();
        assert_eq!((b[4], b[5], b[6]), (1, 0, 0), "humidity is byte 4");
    }

    #[test]
    fn clock_weather_sets_byte_5_only() {
        let p = ClockPacket {
            weather: true,
            ..Default::default()
        };
        let b = p.to_bytes();
        assert_eq!(
            (b[4], b[5], b[6]),
            (0, 1, 0),
            "weather is byte 5 — putting it in byte 4 turns on HUMIDITY on the \
             device, which is exactly the R67 defect"
        );
    }

    #[test]
    fn clock_date_sets_byte_6_only() {
        let p = ClockPacket {
            date: true,
            ..Default::default()
        };
        let b = p.to_bytes();
        assert_eq!((b[4], b[5], b[6]), (0, 0, 1), "date is byte 6");
    }

    #[test]
    fn clock_carries_the_callers_colour() {
        // device.show_clock hardcoded 0xFFFFFF and dropped the wall's colour.
        let p = ClockPacket {
            rgb: [0x12, 0x34, 0x56],
            ..Default::default()
        };
        let b = p.to_bytes();
        assert_eq!(&b[7..10], &[0x12, 0x34, 0x56]);
    }

    #[test]
    fn clock_full_canonical_layout() {
        let p = ClockPacket {
            env: 0,
            twentyfour: true,
            style: 7,
            active: true,
            humidity: true,
            weather: false,
            date: true,
            rgb: [0xAA, 0xBB, 0xCC],
        };
        assert_eq!(
            p.to_bytes(),
            [0, 1, 7, 1, 1, 0, 1, 0xAA, 0xBB, 0xCC],
            "layout is [env, 24h, style, active, humidity, weather, date, R, G, B]"
        );
    }

    #[test]
    fn clock_style_is_clamped_to_the_device_range() {
        let p = ClockPacket {
            style: 200,
            ..Default::default()
        };
        assert_eq!(p.to_bytes()[2], 15);
    }

    // ── Lighting: every mode is a DISTINCT packet ────────────────────────

    #[test]
    fn every_ambient_mode_produces_a_distinct_packet() {
        // The R67 ambient defect in one assertion: the handler hardcoded the
        // type byte, so all five modes serialized identically.
        let modes = [
            LightingType::PlainColor,
            LightingType::Love,
            LightingType::Plants,
            LightingType::Sleeping,
            LightingType::NoMosquito,
        ];
        let packets: Vec<[u8; 10]> = modes
            .iter()
            .map(|&kind| {
                LightPacket {
                    kind,
                    ..Default::default()
                }
                .to_bytes()
            })
            .collect();
        let distinct: std::collections::HashSet<_> = packets.iter().collect();
        assert_eq!(
            distinct.len(),
            modes.len(),
            "all {} ambient modes must serialize differently, got {} distinct",
            modes.len(),
            distinct.len()
        );
    }

    #[test]
    fn lighting_type_lands_in_byte_5() {
        for (kind, want) in [
            (LightingType::PlainColor, 0u8),
            (LightingType::Love, 1),
            (LightingType::Plants, 2),
            (LightingType::Sleeping, 3),
            (LightingType::NoMosquito, 4),
        ] {
            let b = LightPacket {
                kind,
                ..Default::default()
            }
            .to_bytes();
            assert_eq!(b[5], want, "{kind:?} must serialize its own type byte");
        }
    }

    #[test]
    fn lighting_power_off_is_representable() {
        // `power` was read only from kwargs, never positionally — it defaulted
        // to true and happened to be right. Luck is not correctness.
        let b = LightPacket {
            power: false,
            ..Default::default()
        }
        .to_bytes();
        assert_eq!(b[6], 0);
    }

    #[test]
    fn lighting_full_canonical_layout() {
        let p = LightPacket {
            rgb: [0x00, 0xFF, 0xCC],
            brightness: 80,
            kind: LightingType::Plants,
            power: true,
        };
        assert_eq!(
            p.to_bytes(),
            [0x01, 0x00, 0xFF, 0xCC, 80, 2, 1, 0, 0, 0],
            "layout is [channel, R, G, B, brightness, type, power, 0, 0, 0]"
        );
    }

    #[test]
    fn brightness_is_clamped() {
        let b = LightPacket {
            brightness: 255,
            ..Default::default()
        }
        .to_bytes();
        assert_eq!(b[4], 100);
    }

    #[test]
    fn unknown_lighting_type_falls_back_to_plain() {
        assert_eq!(LightingType::from_i64(99), LightingType::PlainColor);
        assert_eq!(LightingType::from_i64(-1), LightingType::PlainColor);
        assert_eq!(LightingType::from_i64(2), LightingType::Plants);
    }

    // ── Channel switches stay 10 bytes ───────────────────────────────────

    #[test]
    fn channel_switches_are_padded_to_ten_bytes() {
        // Short packets are silently ignored by the device.
        assert_eq!(
            channel_switch(Channel::Design),
            [5, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        );
        assert_eq!(
            channel_switch(Channel::Scoreboard),
            [6, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        );
    }

    #[test]
    fn vj_effects_are_one_indexed_on_the_wire() {
        assert_eq!(vj_effect(0)[1], 1, "UI 0 is device 1");
        assert_eq!(vj_effect(15)[1], 16);
        assert_eq!(
            vj_effect(255)[1],
            255,
            "saturates rather than wrapping to 0"
        );
    }

    #[test]
    fn visualization_is_zero_indexed_on_the_wire() {
        assert_eq!(visualization(4)[1], 4);
    }
}
