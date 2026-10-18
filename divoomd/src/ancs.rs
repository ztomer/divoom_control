//! The 0x50 (ANCS) notification payload -- one construction site.
//!
//! Two builders had the same mapping: `tools.show_notification` and the
//! macOS notification forwarder. A bare app type skips wire value 8, so
//! types 8 and up go out one higher, and both computed that as
//! `app_type + 1` on a `u8`: type 255 -- any request value of 255 or more,
//! saturated -- overflowed, a panic in a debug build and a silent 0 in a
//! release one (found by the P5.10 failure sweep). Now there is one mapping,
//! and the type with no wire value is refused.

use crate::wire::WireNarrow;

/// The most text the panel shows, in bytes.
const MAX_TEXT: usize = 128;

/// The payload for `app_type` with `text`; a bare type when `text` is
/// empty. `None` for a bare type with no wire value (255).
#[must_use]
pub fn payload(app_type: u8, text: &str) -> Option<Vec<u8>> {
    if text.is_empty() {
        return bare(app_type).map(|b| vec![b]);
    }
    Some(with_text(app_type, text))
}

/// The wire value of a bare app type, or `None` when it has none.
#[must_use]
pub const fn bare(app_type: u8) -> Option<u8> {
    if app_type >= 8 {
        app_type.checked_add(1)
    } else {
        Some(app_type)
    }
}

/// The type, the text's length and up to [`MAX_TEXT`] bytes of text.
#[must_use]
pub fn with_text(app_type: u8, text: &str) -> Vec<u8> {
    let bytes = &text.as_bytes()[..text.len().min(MAX_TEXT)];
    let mut p = Vec::with_capacity(2 + bytes.len());
    p.push(app_type);
    p.push(bytes.len().byte());
    p.extend_from_slice(bytes);
    p
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bare_type_skips_eight_and_the_last_has_no_wire_value() {
        assert_eq!(bare(7), Some(7));
        assert_eq!(bare(8), Some(9));
        assert_eq!(bare(254), Some(255));
        assert_eq!(bare(255), None);
        assert_eq!(payload(255, ""), None);
        assert_eq!(payload(255, "hi"), Some(vec![255, 2, b'h', b'i']));
    }

    #[test]
    fn text_is_cut_at_the_panel_limit() {
        let long = "x".repeat(300);
        let p = with_text(1, &long);
        assert_eq!(p.len(), 2 + MAX_TEXT);
        assert_eq!(p[1], 128);
    }
}
