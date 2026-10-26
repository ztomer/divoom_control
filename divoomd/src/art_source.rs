//! What an image IS decides whether it may be scaled to a panel (D14).
//!
//! # The class
//!
//! Pixel art is drawn pixel by pixel for ONE panel size. Scaled to another --
//! a 64x64 gallery piece squeezed onto a 16x16 panel -- every fourth pixel
//! survives and the piece is unrecognisable. Five paths did exactly that, each
//! through a resize that defaulted on: the custom-art page (`resolve_to_rgb16x16`),
//! the monthly-best push and its stored page (always 16, gallery asked for
//! every size), `sync_artwork` (`default_size` 16), the GUI's gallery play
//! (`display.show_image` at 16 whatever the panel), and the wall.
//!
//! A photograph is the opposite case: album art has no native panel size, and
//! scaling it is the only way to show it at all.
//!
//! # The rule, as a type
//!
//! [`Source`] has no default and no "scale anyway" knob. Every image that
//! reaches a panel is prepared through `image_proc::prepare`, which takes a
//! `Source`; pixel art whose native size is not the panel's is REFUSED with
//! the reason ([`mismatch`]), never scaled. On the wire the same choice is the
//! `art` argument of `display.show_image` and the wall's `show_image`, and it
//! is required: a caller that does not say what it is sending is refused,
//! rather than given the scaler by default.

use serde_json::Value;

use crate::image_fit::Fit;

/// What an image is, which is what decides whether it may be scaled.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    /// Art drawn for one panel size (cloud gallery, hot channel, custom art,
    /// monthly best). Shown only on a panel of exactly that size.
    PixelArt,
    /// A picture with no native panel size (album art, a photo, a rendered
    /// card), scaled under the stated policy.
    Picture(Fit),
}

/// The wire names of the `art` argument, for refusals and tool schemas.
pub const WIRE_NAMES: [&str; 2] = ["pixel", "picture"];

impl Source {
    /// The `art` argument as sent: `"pixel"` or `"picture"` (scaled `exact`).
    ///
    /// # Errors
    ///
    /// When it is absent or neither name: there is no default, because the
    /// default used to be "scale it", and that is the bug.
    pub fn from_wire(art: Option<&str>) -> Result<Self, String> {
        match art {
            Some("pixel") => Ok(Self::PixelArt),
            Some("picture") => Ok(Self::Picture(Fit::Exact)),
            Some(other) => Err(format!(
                "art must be one of {WIRE_NAMES:?} (got {other:?}): pixel art is never scaled, \
                 a picture is"
            )),
            None => Err(format!(
                "say what the image is: art must be one of {WIRE_NAMES:?} -- pixel art is shown \
                 only on a panel of its own size, a picture is scaled to fit"
            )),
        }
    }
}

/// The refusal for pixel art drawn at `w`x`h` sent to a `pw`x`ph` screen.
#[must_use]
pub fn mismatch(w: u32, h: u32, pw: u32, ph: u32) -> String {
    format!(
        "this pixel art is drawn for {w}x{h} and the panel is {pw}x{ph}; pixel art is never \
         rescaled to another panel size -- choose art drawn for {pw}x{ph}"
    )
}

/// `Ok` when pixel art of `w`x`h` is native to a `pw`x`ph` screen.
///
/// # Errors
///
/// [`mismatch`] when it is not.
pub fn native(w: u32, h: u32, pw: u32, ph: u32) -> Result<(), String> {
    if (w, h) == (pw, ph) {
        Ok(())
    } else {
        Err(mismatch(w, h, pw, ph))
    }
}

/// The pixel size an image file declares, read from its header only.
///
/// # Errors
///
/// When the bytes are not an image the decoder recognises.
pub fn image_dims(data: &[u8]) -> Result<(u32, u32), String> {
    image::ImageReader::new(std::io::Cursor::new(data))
        .with_guessed_format()
        .map_err(|e| format!("image header: {e}"))?
        .into_dimensions()
        .map_err(|e| format!("image header: {e}"))
}

/// The cloud's `FileSize` bit for a square panel edge -- the APK's own table
/// (`CloudWorksDetailsAdapter`: 1=16x16, 2=32x32, 4=64x64, 16=128x128,
/// 32=256x256).
#[must_use]
pub const fn size_bit(pixels: u32) -> Option<i64> {
    match pixels {
        16 => Some(1),
        32 => Some(2),
        64 => Some(4),
        128 => Some(16),
        256 => Some(32),
        _ => None,
    }
}

/// The panel edge a single cloud `FileSize` bit stands for.
#[must_use]
pub const fn pixels_of_bit(bit: i64) -> Option<u32> {
    match bit {
        1 => Some(16),
        2 => Some(32),
        4 => Some(64),
        16 => Some(128),
        32 => Some(256),
        _ => None,
    }
}

/// Keep only the gallery items drawn for exactly `bit`'s size.
///
/// The cloud's `FileSize` request field is a FILTER HINT, and every item
/// states its own size in its own `FileSize`; an item that does not state the
/// requested size cannot be shown natively, so it is not listed. Returns how
/// many items were dropped. A `bit` that is not a single size (127 = "all")
/// filters nothing: that request is not for one panel.
pub fn keep_native(response: &mut Value, bit: i64) -> usize {
    if pixels_of_bit(bit).is_none() {
        return 0;
    }
    let Some(list) = response.get_mut("FileList").and_then(Value::as_array_mut) else {
        return 0;
    };
    let before = list.len();
    list.retain(|item| item.get("FileSize").and_then(Value::as_i64) == Some(bit));
    before - list.len()
}

#[cfg(test)]
#[path = "art_source_tests.rs"]
mod tests;
