//! Byte-exact tests for the typed wire packets.
//!
//! Split out of `packets.rs` in R67 when that file crossed the house 500-line
//! cap. These are the regression tests for class C1 — one wire packet, one
//! construction site — and for the temperature encoding, which is correct only
//! for the negative half of its range by two's-complement luck if written by
//! hand.

#[cfg(test)]
mod tests {
    use crate::packets::*;

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

    // ── Weather ──────────────────────────────────────────────────────────

    #[test]
    fn positive_temperatures_encode_directly() {
        assert_eq!(encode_temperature(0), 0);
        assert_eq!(encode_temperature(21), 21);
        assert_eq!(encode_temperature(127), 127);
    }

    #[test]
    fn negative_temperatures_are_twos_complement() {
        // The half of the range that a naive cast gets wrong-looking and a
        // naive `abs()` gets wrong outright. Pinned against
        // divoom_lib/system/weather.py's (256 + celsius) & 0xFF.
        assert_eq!(encode_temperature(-1), 255);
        assert_eq!(encode_temperature(-5), 251);
        assert_eq!(encode_temperature(-40), 216);
        assert_eq!(encode_temperature(-128), 128);
    }

    #[test]
    fn the_python_formula_and_this_one_agree_across_the_whole_range() {
        // (256 + c) & 0xFF for c < 0, else c & 0xFF — every representable input.
        for c in i8::MIN..=i8::MAX {
            let python = if c < 0 {
                ((256 + c as i32) & 0xFF) as u8
            } else {
                (c as i32 & 0xFF) as u8
            };
            assert_eq!(encode_temperature(c), python, "disagreement at {c}C");
        }
    }

    #[test]
    fn a_weather_packet_is_temperature_then_icon() {
        let p = WeatherPacket {
            temperature_c: 21,
            weather: WeatherType::Rain,
        };
        assert_eq!(p.to_bytes(), [21, 6]);
    }

    #[test]
    fn a_freezing_weather_packet_survives_the_round_trip() {
        let p = WeatherPacket {
            temperature_c: -7,
            weather: WeatherType::Snow,
        };
        assert_eq!(p.to_bytes(), [249, 8]);
    }

    #[test]
    fn unknown_weather_codes_fall_back_to_clear() {
        assert_eq!(WeatherType::from_i64(99), WeatherType::Clear);
        assert_eq!(WeatherType::from_i64(-1), WeatherType::Clear);
        assert_eq!(WeatherType::from_i64(8), WeatherType::Snow);
    }

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
