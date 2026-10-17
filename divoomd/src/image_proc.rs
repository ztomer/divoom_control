//! Image loading and resizing — port of `divoom_lib/utils/image_processing.py`
//! `process_image()`.
//!
//! Takes raw file bytes, returns per-frame `(rgb, w, h, time_ms)` tuples ready
//! to be encoded by `image_encode` and streamed via 0x8B.
//!
//! NEAREST resampling matches the Python `Image.Resampling.NEAREST` used there;
//! keeping the same filter keeps pixel art crisp and avoids blurring on upscale.
//!
//! Animated GIFs are decoded frame-by-frame with per-frame delay timing.
//! Single-frame inputs (PNG, JPEG, static GIF) produce a 1-element vector.

use image::{AnimationDecoder, DynamicImage};

use crate::image_fit::{fit_frame, limit_palette, Fit};

/// One decoded frame: (`rgb_bytes`, w, h, `time_ms`).
pub type Frame = (Vec<u8>, i32, i32, u16);

/// Load image bytes (PNG, JPEG, or GIF) and resize each frame to `size × size`.
/// `default_time_ms` is used for static images and GIF frames with no delay.
///
/// CPU-bound — callers should invoke via `tokio::task::spawn_blocking`.
///
/// # Errors
///
/// When the bytes are not an image this decoder recognises, or a GIF frame
/// cannot be read. A file that decodes but is the wrong size is resized rather
/// than refused.
pub fn process_image_bytes(
    data: Vec<u8>,
    size: u32,
    default_time_ms: u16,
) -> Result<Vec<Frame>, String> {
    process_image_bytes_with(data, size, Fit::Exact, default_time_ms)
}

/// [`process_image_bytes`] under a stated resize policy (P4.3).
///
/// Every frame leaves here with at most 256 colours ([`limit_palette`]): the
/// encoder refuses more, and past 16 px a photograph always has more.
///
/// # Errors
///
/// As [`process_image_bytes`], and [`Fit::None`] with an image that is not
/// already `size`x`size`.
pub fn process_image_bytes_with(
    data: Vec<u8>,
    size: u32,
    policy: Fit,
    default_time_ms: u16,
) -> Result<Vec<Frame>, String> {
    if data.len() >= 3 && &data[0..3] == b"GIF" {
        process_gif(data, size, policy, default_time_ms)
    } else {
        process_static(&data, size, policy, default_time_ms)
    }
}

/// One frame of the panel's size, palette-limited.
fn frame(img: &DynamicImage, size: u32, policy: Fit, time_ms: u16) -> Result<Frame, String> {
    let mut rgb = fit_frame(img, size, policy)?.into_raw();
    limit_palette(&mut rgb);
    let edge = i32::try_from(size).expect("panel edge fits i32");
    Ok((rgb, edge, edge, time_ms))
}

fn process_static(data: &[u8], size: u32, policy: Fit, time_ms: u16) -> Result<Vec<Frame>, String> {
    let img = image::load_from_memory(data).map_err(|e| format!("image load: {e}"))?;
    Ok(vec![frame(&img, size, policy, time_ms)?])
}

fn process_gif(
    data: Vec<u8>,
    size: u32,
    policy: Fit,
    default_time_ms: u16,
) -> Result<Vec<Frame>, String> {
    use image::codecs::gif::GifDecoder;
    let decoder =
        GifDecoder::new(std::io::Cursor::new(data)).map_err(|e| format!("gif decoder: {e}"))?;
    let frames = decoder
        .into_frames()
        .collect_frames()
        .map_err(|e| format!("gif frames: {e}"))?;
    if frames.is_empty() {
        return Err("GIF has no frames".into());
    }
    let mut out = Vec::with_capacity(frames.len());
    for gif_frame in frames {
        let (numer, denom) = gif_frame.delay().numer_denom_ms();
        // numer/denom milliseconds; minimum 50ms to avoid zero-delay frame hangs
        let time_ms = if denom == 0 {
            default_time_ms
        } else {
            u16::try_from(numer / denom.max(1))
                .unwrap_or(u16::MAX)
                .max(50)
        };
        let img = DynamicImage::ImageRgba8(gif_frame.into_buffer());
        out.push(frame(&img, size, policy, time_ms)?);
    }
    Ok(out)
}
