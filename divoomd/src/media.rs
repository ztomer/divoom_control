//! `resolve_to_gif` — port of Python `media_decoder.resolve_to_gif`. Turns any
//! known cloud download into image bytes the unified `display.show_image` path can
//! render (which then resizes NEAREST to the device size and 0x8B-streams):
//!
//! - plain GIF / PNG / JPG, and magic-43 embeds → handed back as-is
//! - magic 9 / 18 / 26 (AES; 18/26 also LZO + tiled) → decoded frames → GIF
//! - 0xAA hot (palette-delta) → decoded frames → GIF
//!
//! Returns None only for genuinely unrecognized payloads (callers fail honestly
//! rather than raw-stream undecodable bytes, which sticks the device).

use image::codecs::gif::{GifEncoder, Repeat};
use image::{Delay, Frame, RgbaImage};

use crate::art_codec::{
    decode_cloud_magic18_26, decode_cloud_magic9, decode_hot_file, resolve_to_image_bytes,
};

/// Encode RGB frames (`(rgb, duration_ms)`, each `w*h*3` bytes) into an animated
/// GIF that loops forever.
fn encode_frames_to_gif(frames: &[(Vec<u8>, u32)], w: u32, h: u32) -> Option<Vec<u8>> {
    if frames.is_empty() || w == 0 || h == 0 {
        return None;
    }
    let expected = (w * h * 3) as usize;
    let mut buf = Vec::new();
    {
        let mut enc = GifEncoder::new(&mut buf);
        enc.set_repeat(Repeat::Infinite).ok()?;
        for (rgb, dur_ms) in frames {
            if rgb.len() < expected {
                return None;
            }
            let mut rgba = Vec::with_capacity((w * h * 4) as usize);
            for px in rgb[..expected].as_chunks::<3>().0 {
                rgba.extend_from_slice(&[px[0], px[1], px[2], 0xFF]);
            }
            let img = RgbaImage::from_raw(w, h, rgba)?;
            let frame = Frame::from_parts(img, 0, 0, Delay::from_numer_denom_ms(*dur_ms, 1));
            enc.encode_frame(frame).ok()?;
        }
    }
    Some(buf)
}

/// Resolve a downloaded cloud payload to renderable image bytes (GIF/PNG/JPG).
pub fn resolve_to_gif(raw: &[u8]) -> Option<Vec<u8>> {
    if raw.len() < 4 {
        return None;
    }
    // Directly-renderable images + magic-43 embeds — pass through unchanged.
    if let Some(img) = resolve_to_image_bytes(raw) {
        return Some(img);
    }
    match raw[0] {
        9 => {
            let (frames, dur) = decode_cloud_magic9(raw)?;
            let fr: Vec<(Vec<u8>, u32)> = frames.into_iter().map(|f| (f, dur)).collect();
            encode_frames_to_gif(&fr, 16, 16)
        }
        18 | 26 => {
            let (frames, w, h, dur) = decode_cloud_magic18_26(raw)?;
            let fr: Vec<(Vec<u8>, u32)> = frames.into_iter().map(|f| (f, dur)).collect();
            encode_frames_to_gif(&fr, w, h)
        }
        0xAA => {
            let frames = decode_hot_file(raw)?;
            encode_frames_to_gif(&frames, 16, 16)
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    //! Verify the full resolve→GIF pipeline offline: decoded cloud frames encode to
    //! a GIF that `display.show_image`'s decoder (`process_image_bytes`) reads back
    //! with the right frame count + size — i.e. the device gets a real renderable
    //! animation, not undecodable bytes.
    use super::*;
    use std::path::PathBuf;

    fn raw(name: &str) -> Vec<u8> {
        std::fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("tests/cloud_fixtures")
                .join(name),
        )
        .expect("fixture")
    }

    #[test]
    fn magic9_resolves_to_decodable_gif() {
        let gif = resolve_to_gif(&raw("magic9.bin")).expect("resolve magic9");
        assert!(gif.starts_with(b"GIF"), "resolved output must be a GIF");
        let frames = crate::image_proc::process_image_bytes(gif, 16, 100).expect("re-decode");
        assert_eq!(frames.len(), 24, "24 frames survive the GIF round-trip");
        assert_eq!((frames[0].1, frames[0].2), (16, 16));
    }

    #[test]
    fn magic18_resolves_to_decodable_gif() {
        let gif = resolve_to_gif(&raw("magic18.bin")).expect("resolve magic18");
        assert!(gif.starts_with(b"GIF"), "resolved output must be a GIF");
        let frames = crate::image_proc::process_image_bytes(gif, 16, 100).expect("re-decode");
        assert_eq!(frames.len(), 6, "6 frames survive the GIF round-trip");
        assert_eq!(
            (frames[0].1, frames[0].2),
            (16, 16),
            "resized to device size"
        );
    }
}
