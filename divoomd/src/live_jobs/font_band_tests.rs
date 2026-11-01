//! The half-size glyphs sit where the vendor's full font puts them.
//!
//! The half blob (`divoom_fond16_default_half.bin`) stores every glyph from
//! row 0 with no baseline: `-` is one row at the top, `.` and `_` too. Drawn as
//! stored, a 16px weather frame wrote -5 degrees as an overline beside a 5
//! (found in the P9.3 backdrop pass, 2026-11-01). The vendor's full font does
//! carry each glyph's place, so the half glyphs take their row from it.

#[cfg(test)]
mod tests {
    use crate::live_jobs::font::{BitmapFont, FONT_BYTES};

    fn ink(ch: char) -> (usize, usize) {
        let rows = BitmapFont::new(FONT_BYTES).rows(ch);
        let lit: Vec<usize> = (0..16).filter(|&r| rows[r] != 0).collect();
        (lit[0], *lit.last().expect("ink"))
    }

    #[test]
    fn a_minus_sits_on_the_digits_middle_row() {
        let (top, bottom) = ink('5');
        let (m, _) = ink('-');
        assert_eq!(
            m,
            usize::midpoint(top, bottom),
            "minus at row {m}, digits span {top}..={bottom}"
        );
    }

    #[test]
    fn a_full_stop_and_an_underscore_sit_on_the_baseline() {
        let (_, base) = ink('0');
        assert_eq!(ink('.').1, base);
        assert!(ink('_').1 >= base);
    }

    #[test]
    fn digits_and_capitals_keep_their_rows() {
        for ch in "0123456789AEHT".chars() {
            assert_eq!(ink(ch).0, 0, "{ch} moved");
        }
    }

    #[test]
    fn short_lowercase_sits_on_the_baseline_not_the_cap_line() {
        let (_, base) = ink('0');
        for ch in "amnorsuvwxz".chars() {
            assert_eq!(ink(ch).1, base, "{ch} floats above the baseline");
        }
    }
}
