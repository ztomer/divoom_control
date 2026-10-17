//! Each policy does what its name says, and the palette limit makes a
//! photograph encodable without touching pixel art.

use super::*;
use image::Rgb;

/// A 2:1 image, every pixel lit, so black in the output can only be padding.
fn wide() -> DynamicImage {
    DynamicImage::ImageRgb8(RgbImage::from_pixel(32, 16, Rgb([200, 40, 40])))
}

fn black_rows(img: &RgbImage) -> usize {
    img.rows()
        .filter(|row| row.clone().all(|p| p.0 == [0, 0, 0]))
        .count()
}

#[test]
fn fit_keeps_the_whole_image_and_pads() {
    let out = fit_frame(&wide(), 16, Fit::Fit).expect("fit");
    assert_eq!(out.dimensions(), (16, 16));
    assert_eq!(black_rows(&out), 8, "a 2:1 image fills half the rows");
    assert_eq!(out.get_pixel(8, 8).0, [200, 40, 40]);
}

#[test]
fn fill_covers_the_panel_and_crops() {
    let out = fit_frame(&wide(), 16, Fit::Fill).expect("fill");
    assert_eq!(out.dimensions(), (16, 16));
    assert_eq!(black_rows(&out), 0, "fill leaves no padding");
}

#[test]
fn exact_stretches() {
    let out = fit_frame(&wide(), 64, Fit::Exact).expect("exact");
    assert_eq!(out.dimensions(), (64, 64));
    assert_eq!(black_rows(&out), 0);
}

#[test]
fn none_takes_only_the_panels_own_size() {
    let err = fit_frame(&wide(), 16, Fit::None).expect_err("32x16 is not 16x16");
    assert!(err.contains("16x16") && err.contains("32x16"), "{err}");
    let square = DynamicImage::ImageRgb8(RgbImage::from_pixel(16, 16, Rgb([1, 2, 3])));
    assert_eq!(
        fit_frame(&square, 16, Fit::None)
            .expect("exact size")
            .dimensions(),
        (16, 16)
    );
}

#[test]
fn every_policy_has_a_distinct_wire_name() {
    for (name, policy) in Fit::ALL {
        assert_eq!(Fit::parse(name), Ok(policy));
    }
    let err = Fit::parse("stretch").expect_err("not a policy");
    assert!(err.contains("fit") && err.contains("none"), "{err}");
}

#[test]
fn a_photograph_becomes_encodable() {
    // 64x64 with 4096 distinct colours: the encoder refuses it as it stands.
    let mut rgb = Vec::with_capacity(64 * 64 * 3);
    for y in 0..64u8 {
        for x in 0..64u8 {
            rgb.extend_from_slice(&[x * 4, y * 4, x.wrapping_add(y)]);
        }
    }
    assert!(crate::image_encode::encode_animation_frame(&rgb, 64, 64, 100).is_err());
    limit_palette(&mut rgb);
    assert!(
        crate::image_encode::encode_animation_frame(&rgb, 64, 64, 100).is_ok(),
        "still more than 256 colours after limit_palette"
    );
}

#[test]
fn pixel_art_that_fits_is_left_alone() {
    let mut rgb: Vec<u8> = (0..=255u8).flat_map(|i| [i, 255 - i, 7]).collect();
    let before = rgb.clone();
    limit_palette(&mut rgb);
    assert_eq!(rgb, before, "256 colours fit; nothing may move");
}
