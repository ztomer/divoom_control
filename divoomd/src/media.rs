//! `resolve_to_gif` — port of Python `media_decoder.resolve_to_gif`.
//!
//! Turns any known cloud download into image bytes the unified
//! `display.show_image` path can render, at the art's OWN size: cloud art is
//! pixel art, shown only on a panel of that size and never rescaled (D14):
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
pub(crate) fn encode_frames_to_gif(frames: &[(Vec<u8>, u32)], w: u32, h: u32) -> Option<Vec<u8>> {
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
#[must_use]
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
        18 => {
            let (frames, w, h, dur) = decode_cloud_magic18_26(raw)?;
            let fr: Vec<(Vec<u8>, u32)> = frames.into_iter().map(|f| (f, dur)).collect();
            encode_frames_to_gif(&fr, w, h)
        }
        // Magic 26 is the app's "Iframe" container (plain length-prefixed
        // 0xAA records, decoded natively by PixelDecode128), not the AES+LZO
        // layout of 18 -- the two were one arm here until 2026-09-13. The
        // 128x128 shape is what the clock-face store ships; anything else
        // still tries the old reading before giving up.
        26 => {
            let (frames, w, h, dur) = crate::art_codec::decode_cloud_magic26(raw)
                .or_else(|| decode_cloud_magic18_26(raw))?;
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

/// Why a payload could not be resolved to an image — the reason a run names.
///
/// The magic byte says WHICH container it is, and for the magic-26 family
/// the first frame's own flag says which shape of it, so the next person
/// knows where to look instead of counting a file that did not arrive.
#[must_use]
pub fn why_not_resolvable(raw: &[u8]) -> String {
    match raw.first().copied() {
        None => "the file was empty".to_string(),
        Some(26) => {
            // The first frame's record starts at byte 10 — a 6-byte container
            // header and the frame's u32 length — and the flag is the
            // record's sixth byte.
            let record = raw.get(10..16).filter(|r| r.first() == Some(&0xAA));
            record.map_or_else(
                || "a magic-26 (0x1A) container this decoder does not read".to_string(),
                |r| {
                    format!(
                        "a magic-26 (0x1A) container with frame flag 0x{:02x} — a frame \
                         shape this decoder does not read",
                        r[5]
                    )
                },
            )
        }
        Some(magic) => format!("a magic-{magic} container this decoder does not read"),
    }
}

#[cfg(test)]
mod tests {
    //! Verify the full resolve→GIF pipeline offline: decoded cloud frames encode to
    //! a GIF that `display.show_image`'s decoder (`image_proc::prepare`) reads back
    //! with the right frame count + size — i.e. the device gets a real renderable
    //! animation, not undecodable bytes.
    use super::*;
    use std::path::PathBuf;

    /// The resolved art as pixel art at its OWN size: cloud art is never
    /// scaled (D14), so the re-decode is at the size the GIF declares.
    fn native_frames(gif: Vec<u8>) -> Vec<crate::image_proc::Frame> {
        let (w, _) = crate::art_source::image_dims(&gif).expect("a GIF header");
        crate::image_proc::prepare(gif, crate::art_source::Source::PixelArt, w, 100)
            .expect("re-decode at the native size")
    }

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
        let frames = native_frames(gif);
        assert_eq!(frames.len(), 24, "24 frames survive the GIF round-trip");
        assert_eq!((frames[0].1, frames[0].2), (16, 16));
    }

    #[test]
    fn magic18_resolves_to_decodable_gif() {
        let gif = resolve_to_gif(&raw("magic18.bin")).expect("resolve magic18");
        assert!(gif.starts_with(b"GIF"), "resolved output must be a GIF");
        let frames = native_frames(gif);
        assert_eq!(frames.len(), 6, "6 frames survive the GIF round-trip");
        assert_eq!(
            (frames[0].1, frames[0].2),
            (32, 32),
            "drawn for a 32x32 panel, and kept at it -- this test used to pin a \
             resize to 16x16 (D14)"
        );
    }

    /// E56: the gallery's magic-26 files are the ones the run used to count
    /// as warnings. They must reach the device as a real animation.
    #[test]
    fn a_gallery_magic26_resolves_to_decodable_gif() {
        let gif = resolve_to_gif(&raw("gallery_magic26_jack_skellington.bin"))
            .expect("resolve the gallery's magic-26");
        assert!(gif.starts_with(b"GIF"), "resolved output must be a GIF");
        let frames = native_frames(gif);
        assert_eq!(frames.len(), 2, "both frames survive the GIF round-trip");
        assert_eq!(
            (frames[0].1, frames[0].2),
            (64, 64),
            "drawn for a 64x64 panel, and kept at it -- this test used to pin a \
             resize to 16x16, which is the owner's 'it looks awful' (D14)"
        );
        assert_eq!(frames[0].3, 500, "the frame's own display time survives");
    }

    /// D14: the gallery's 64x64 piece is refused on a 16x16 panel, never
    /// squeezed onto it.
    #[test]
    fn a_gallery_64x64_piece_is_refused_on_a_16x16_panel() {
        let gif = resolve_to_gif(&raw("gallery_magic26_jack_skellington.bin")).expect("resolve");
        let why = crate::image_proc::prepare(gif, crate::art_source::Source::PixelArt, 16, 100)
            .expect_err("64x64 art on a 16x16 panel")
            .to_string();
        assert!(why.contains("64x64") && why.contains("16x16"), "{why}");
    }
}
