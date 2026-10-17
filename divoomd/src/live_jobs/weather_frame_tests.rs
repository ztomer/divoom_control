//! The weather frame: right size at every edge, readable digits, and icons
//! that differ by SHAPE, not only by colour.

use super::*;

const ALL: [WeatherType; 6] = [
    WeatherType::Clear,
    WeatherType::CloudySky,
    WeatherType::Rain,
    WeatherType::Snow,
    WeatherType::Thunderstorm,
    WeatherType::Fog,
];

/// Which pixels are lit, colour discarded: what a reader who cannot tell red
/// from green (or a greyscale photo) still sees.
fn mask(rgb: &[u8]) -> Vec<bool> {
    rgb.chunks(3).map(|p| (p[0], p[1], p[2]) != BG).collect()
}

#[test]
fn every_size_the_daemon_accepts_yields_a_full_frame() {
    for size in [8, 12, 16, 24, 32, 48, 64] {
        for w in ALL {
            let f = render_weather(-12, w, size);
            assert_eq!(f.len(), (size * size * 3) as usize, "{size}");
            assert!(mask(&f).iter().any(|&lit| lit), "{size}: blank frame");
        }
    }
}

#[test]
fn the_icons_differ_in_greyscale_at_every_panel_class() {
    for size in [16, 32, 64] {
        let masks: Vec<_> = ALL
            .iter()
            .map(|&w| mask(&render_weather(20, w, size)))
            .collect();
        for i in 0..masks.len() {
            for j in i + 1..masks.len() {
                assert_ne!(
                    masks[i], masks[j],
                    "{:?} and {:?} differ only by colour at {size}",
                    ALL[i], ALL[j]
                );
            }
        }
    }
}

#[test]
fn the_temperature_changes_the_digits_and_only_the_digits() {
    let a = mask(&render_weather(21, WeatherType::Clear, 16));
    let b = mask(&render_weather(35, WeatherType::Clear, 16));
    let icon_rows = 9 * 16; // the icon occupies rows 1..=8
    assert_eq!(a[..icon_rows], b[..icon_rows], "the icon moved");
    assert_ne!(a[icon_rows..], b[icon_rows..], "the digits did not change");
}

#[test]
fn a_tiny_preview_shows_the_reading_when_it_fits_and_the_icon_when_not() {
    // "7" fits an 8x8: the reading, whatever the sky.
    assert_eq!(
        render_weather(7, WeatherType::Rain, 8),
        render_weather(7, WeatherType::Snow, 8)
    );
    assert_ne!(
        render_weather(7, WeatherType::Rain, 8),
        render_weather(8, WeatherType::Rain, 8)
    );
    // "-12" does not: never a clipped "-1", the icon instead.
    assert_eq!(
        render_weather(-12, WeatherType::Rain, 8),
        render_weather(-13, WeatherType::Rain, 8)
    );
    assert_ne!(
        render_weather(-12, WeatherType::Rain, 8),
        render_weather(-12, WeatherType::Snow, 8)
    );
}

#[test]
fn the_degree_mark_goes_before_any_digit_is_clipped() {
    // 13 px of digits + gap + 2 px mark = 16: all of it.
    assert_eq!(degree_mark(13, 2, 1, 16), Some(2));
    // 14 px of digits: the mark would not fit, the digits do.
    assert_eq!(degree_mark(14, 2, 1, 16), Some(0));
    assert_eq!(degree_mark(16, 2, 1, 16), Some(0));
    // 17 px: nothing, rather than a reading with a digit cut off.
    assert_eq!(degree_mark(17, 2, 1, 16), None);
    // Scale counts: 15 glyph px at x2 is 30 of a 32 panel, mark dropped.
    assert_eq!(degree_mark(15, 3, 2, 32), Some(0));
}
