//! D14's rules, pure: what the type admits, and what the gallery lists.

use super::*;
use serde_json::json;

#[test]
fn the_art_argument_has_no_default() {
    assert_eq!(Source::from_wire(Some("pixel")), Ok(Source::PixelArt));
    assert_eq!(
        Source::from_wire(Some("picture")),
        Ok(Source::Picture(Fit::Exact))
    );
    let none = Source::from_wire(None).expect_err("a missing art is refused");
    assert!(none.contains("pixel"), "{none}");
    assert!(Source::from_wire(Some("scale")).is_err());
}

#[test]
fn pixel_art_is_native_only_at_its_own_size() {
    assert!(native(16, 16, 16, 16).is_ok());
    let why = native(64, 64, 16, 16).expect_err("64x64 art on a 16x16 panel");
    assert!(
        why.contains("64x64") && why.contains("16x16") && why.contains("never"),
        "{why}"
    );
}

#[test]
fn the_size_bits_are_the_apks_table_both_ways() {
    for (px, bit) in [(16, 1), (32, 2), (64, 4), (128, 16), (256, 32)] {
        assert_eq!(size_bit(px), Some(bit));
        assert_eq!(pixels_of_bit(bit), Some(px));
    }
    assert_eq!(size_bit(48), None);
    assert_eq!(pixels_of_bit(127), None);
}

fn listing() -> serde_json::Value {
    json!({"ReturnCode": 0, "FileList": [
        {"FileId": "a", "FileSize": 1},
        {"FileId": "b", "FileSize": 4},
        {"FileId": "c", "FileSize": 2},
        {"FileId": "d"},
    ]})
}

fn ids(v: &serde_json::Value) -> Vec<&str> {
    v["FileList"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["FileId"].as_str().unwrap())
        .collect()
}

#[test]
fn a_16x16_panel_is_listed_only_16x16_art() {
    let mut v = listing();
    assert_eq!(keep_native(&mut v, 1), 3);
    assert_eq!(ids(&v), ["a"]);
}

#[test]
fn a_64x64_panel_is_listed_only_64x64_art() {
    let mut v = listing();
    assert_eq!(keep_native(&mut v, 4), 3);
    assert_eq!(ids(&v), ["b"]);
}

#[test]
fn a_request_for_every_size_filters_nothing() {
    let mut v = listing();
    assert_eq!(keep_native(&mut v, 127), 0);
    assert_eq!(ids(&v).len(), 4);
}
