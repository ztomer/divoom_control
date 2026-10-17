//! One case per model class, with real advertised names.

use super::*;

fn px(name: &str) -> (Option<&'static str>, Option<u32>) {
    let p = from_name(Some(name));
    (p.model, p.pixels)
}

#[test]
fn sixteen_pixel_panels() {
    // The four panels on the owner's bench, by the names they advertise.
    assert_eq!(px("Pixoo-light"), (Some("Pixoo"), Some(16)));
    assert_eq!(px("Tivoo-Max-light"), (Some("TivooMax"), Some(16)));
    assert_eq!(px("Ditoo-light"), (Some("DITOO"), Some(16)));
    assert_eq!(px("Timoo-light-4"), (Some("TIMOO"), Some(16)));
}

#[test]
fn thirty_two_pixel_panels() {
    assert_eq!(px("Pixoo-Max-light"), (Some("PIXOO_MAX"), Some(32)));
    // First-match order: "Tivoo-Max32" must win over "Tivoo-Max".
    assert_eq!(px("Tivoo-Max32-light"), (Some("TivoomMax32"), Some(32)));
}

#[test]
fn sixty_four_pixel_panels() {
    assert_eq!(px("Pixoo64-light"), (Some("Pixoo64Wifi"), Some(64)));
    assert_eq!(px("CyberBag-light"), (Some("CyberBag"), Some(64)));
    assert_eq!(px("DiPow-65"), (Some("Dipow65"), Some(64)));
}

#[test]
fn one_twenty_eight_and_two_fifty_six_pixel_panels() {
    assert_eq!(px("Divoom MiniToo"), (Some("MiniToo"), Some(128)));
    assert_eq!(px("Divoom Tiivoo 2"), (Some("TivooLcd"), Some(128)));
    assert_eq!(px("Divoom Emodo"), (Some("DigitalBadge"), Some(256)));
}

#[test]
fn an_unmatched_name_says_its_size_is_a_default_and_no_name_says_unknown() {
    assert_eq!(
        from_name(Some("MockDitoo")),
        Panel {
            model: None,
            pixels: Some(16),
            source: "default"
        }
    );
    for none in [None, Some("")] {
        assert_eq!(
            from_name(none),
            Panel {
                model: None,
                pixels: None,
                source: "unknown"
            }
        );
    }
}

#[test]
fn every_model_the_name_table_yields_has_a_pixel_class() {
    for (_, model) in NAME_PREFIXES {
        assert!(
            matches!(pixels_of(model), 16 | 32 | 64 | 128 | 256),
            "{model}"
        );
    }
}
