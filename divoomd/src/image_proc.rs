//! Image loading and resizing — port of `divoom_lib/utils/image_processing.py`
//! `process_image()`. Takes raw file bytes, returns per-frame `(rgb, w, h, time_ms)`
//! tuples ready to be encoded by `NativeEncoder` and streamed via 0x8B.
//!
//! NEAREST resampling matches the Python `Image.Resampling.NEAREST` used there;
//! keeping the same filter keeps pixel art crisp and avoids blurring on upscale.
//!
//! Animated GIFs are decoded frame-by-frame with per-frame delay timing.
//! Single-frame inputs (PNG, JPEG, static GIF) produce a 1-element vector.

use image::{imageops::FilterType, AnimationDecoder, DynamicImage};

/// One decoded frame: (rgb_bytes, w, h, time_ms).
pub type Frame = (Vec<u8>, i32, i32, u16);

/// Load image bytes (PNG, JPEG, or GIF) and resize each frame to `size × size`.
/// `default_time_ms` is used for static images and GIF frames with no delay.
///
/// CPU-bound — callers should invoke via `tokio::task::spawn_blocking`.
pub fn process_image_bytes(
    data: Vec<u8>,
    size: u32,
    default_time_ms: u16,
) -> Result<Vec<Frame>, String> {
    if data.len() >= 3 && &data[0..3] == b"GIF" {
        process_gif(data, size, default_time_ms)
    } else {
        process_static(&data, size, default_time_ms)
    }
}

fn process_static(data: &[u8], size: u32, time_ms: u16) -> Result<Vec<Frame>, String> {
    let img = image::load_from_memory(data).map_err(|e| format!("image load: {e}"))?;
    let img = img.resize_exact(size, size, FilterType::Nearest);
    let rgb = img.to_rgb8().into_raw();
    Ok(vec![(rgb, size as i32, size as i32, time_ms)])
}

fn process_gif(data: Vec<u8>, size: u32, default_time_ms: u16) -> Result<Vec<Frame>, String> {
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
    for frame in frames {
        let (numer, denom) = frame.delay().numer_denom_ms();
        // numer/denom milliseconds; minimum 50ms to avoid zero-delay frame hangs
        let time_ms = if denom == 0 {
            default_time_ms
        } else {
            ((numer / denom.max(1)) as u16).max(50)
        };
        let rgba = frame.into_buffer();
        let img = DynamicImage::ImageRgba8(rgba).resize_exact(size, size, FilterType::Nearest);
        let rgb = img.to_rgb8().into_raw();
        out.push((rgb, size as i32, size as i32, time_ms));
    }
    Ok(out)
}
