//! Fitting an image to a panel, and to the panel's palette (P4.3).
//!
//! Two things stood between an arbitrary image and a 64x64 panel. The MCP
//! `show_image` resized to 16x16 ("Device size is 16 for now"), so a 64x64
//! panel got a quarter of its pixels. And past 16 px a photograph has far more
//! than the 256 colours the 0x8B frame's palette byte can address, so the
//! encoder refuses it outright ("more than 256 unique colours") -- every image
//! path at 32/64 px failed on real photographs, album covers included.
//!
//! [`Fit`] is the stated resize policy; [`limit_palette`] reduces a frame to
//! 256 colours only when it has more, so pixel art that already fits is left
//! byte-for-byte alone.

use image::{imageops::FilterType, DynamicImage, RgbImage};

use crate::image_encode::PALETTE_MAX;

/// How an image that is not the panel's shape becomes the panel's shape.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fit {
    /// Scale to fit inside, keep the aspect ratio, pad with black.
    Fit,
    /// Scale to cover, keep the aspect ratio, crop the overflow (centred).
    Fill,
    /// Scale each axis to the panel, distorting if the aspect differs.
    Exact,
    /// No scaling: the image must already be the panel's size.
    None,
}

impl Fit {
    /// Every policy, by wire name.
    pub const ALL: [(&'static str, Self); 4] = [
        ("fit", Self::Fit),
        ("fill", Self::Fill),
        ("exact", Self::Exact),
        ("none", Self::None),
    ];

    /// The policy named `name`.
    ///
    /// # Errors
    ///
    /// When `name` is none of [`Self::ALL`]; the message lists them.
    pub fn parse(name: &str) -> Result<Self, String> {
        Self::ALL
            .iter()
            .find(|(n, _)| *n == name)
            .map(|(_, f)| *f)
            .ok_or_else(|| {
                let names: Vec<&str> = Self::ALL.iter().map(|(n, _)| *n).collect();
                format!("resize must be one of {names:?} (got {name:?})")
            })
    }
}

/// `img` as a `size`x`size` RGB frame under `policy`.
///
/// Scaling is nearest-neighbour, the filter every other image path here uses:
/// pixel art stays crisp, and a panel this small shows the difference.
///
/// # Errors
///
/// [`Fit::None`] with an image that is not already `size`x`size`.
pub fn fit_frame(img: &DynamicImage, size: u32, policy: Fit) -> Result<RgbImage, String> {
    let (w, h) = (img.width(), img.height());
    match policy {
        Fit::None if (w, h) == (size, size) => Ok(img.to_rgb8()),
        Fit::None => Err(format!(
            "resize \"none\" needs a {size}x{size} image for this panel; this one is {w}x{h} \
             (pass resize \"fit\", \"fill\" or \"exact\" to scale it)"
        )),
        Fit::Exact => Ok(img.resize_exact(size, size, FilterType::Nearest).to_rgb8()),
        Fit::Fill => Ok(img
            .resize_to_fill(size, size, FilterType::Nearest)
            .to_rgb8()),
        Fit::Fit => {
            let scaled = img.resize(size, size, FilterType::Nearest).to_rgb8();
            let mut canvas = RgbImage::new(size, size);
            let x = i64::from((size - scaled.width()) / 2);
            let y = i64::from((size - scaled.height()) / 2);
            image::imageops::overlay(&mut canvas, &scaled, x, y);
            Ok(canvas)
        }
    }
}

/// Reduce raw RGB to at most [`PALETTE_MAX`] distinct colours, in place.
///
/// A frame that already fits is not touched: quantizing pixel art would move
/// colours the artist chose for no reason. One that does not is mapped
/// through a `NeuQuant` palette of 256.
pub fn limit_palette(rgb: &mut [u8]) {
    let mut seen = std::collections::HashSet::with_capacity(PALETTE_MAX + 1);
    let (pixels, _) = rgb.as_chunks::<3>();
    for p in pixels {
        seen.insert(*p);
        if seen.len() > PALETTE_MAX {
            break;
        }
    }
    if seen.len() <= PALETTE_MAX {
        return;
    }
    let rgba: Vec<u8> = pixels
        .iter()
        .flat_map(|p| [p[0], p[1], p[2], 255])
        .collect();
    let quant = color_quant::NeuQuant::new(10, PALETTE_MAX, &rgba);
    let map = quant.color_map_rgb();
    for p in rgb.as_chunks_mut::<3>().0 {
        let i = quant.index_of(&[p[0], p[1], p[2], 255]) * 3;
        p.copy_from_slice(&map[i..i + 3]);
    }
}

#[cfg(test)]
#[path = "image_fit_tests.rs"]
mod tests;
