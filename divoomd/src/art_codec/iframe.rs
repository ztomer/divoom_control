//! The magic-26 "Iframe" frame — the format the app's own native decoder
//! reads with `divoom_image_decode_Iframe`.
//!
//! Ported 2026-10-21 from the app's native library (`libtimebox.so`,
//! `divoom_image_decode_Iframe` → `divoom_image_decode_Iframe_in`, read with
//! `llvm-objdump` on the arm64-v8a build), because the monthly-best gallery
//! serves its files in it and NOTHING here could read them: the run counted
//! them as warnings and carried on without saying which (E56).
//!
//! # THE CONTAINER
//!
//! A magic-26 (`0x1A`) file is
//! `[26][frames:u8][speed:u16 BE][rows:u8][cols:u8]` and then, per frame,
//! `[len:u32 BE][record]`. The picture is a grid of 16x16 tiles — `cols`
//! across, `rows` down.
//!
//! # THE RECORD
//!
//! `[0xAA][len:u16 LE][time:u16 LE][flag:u8][...]`, and the flag says how the
//! pixels are coded:
//!
//! | flag | picture | pixels |
//! |---|---|---|
//! | `0x0B` | 64x64 | raw RGB |
//! | `0x0C` | 64x64 | a palette (`ncol`, a u16 LE at offset 6) and the indices, LSB-first |
//! | `0x11` | 128x128 | raw RGB |
//! | `0x12` | 128x128 | a palette and the indices, LSB-first |
//!
//! The quadtree (`0x15`) is read by [`super::fix::decode_fix_128`]. The flag
//! `0x14` is the palette form in the app's "net" colour order — the app
//! converts it with `convert_rgb_local_to_net_128` — and this decoder does
//! not: such a file is refused rather than shown in the wrong colours.
//!
//! # THE TILES
//!
//! The decoder's flat run of pixels is TILE-major — each tile's 16 rows of
//! 16 pixels, one tile after another — and the app's own `AbstractC0882b.p`
//! lays tile `t` at grid `(row = t / cols, col = t % cols)`. That is the
//! picture this decoder returns: row-major, `cols * 16` pixels wide.

use super::fix::bits_for;

/// The picture a flag carries, in pixels (the picture is square).
const fn flag_pixels(flag: u8) -> Option<usize> {
    match flag {
        0x0B | 0x0C => Some(64 * 64),
        0x11 | 0x12 => Some(128 * 128),
        _ => None,
    }
}

/// Raw RGB: the picture's bytes, as they are.
fn raw_pixels(rec: &[u8], pixels: usize) -> Option<Vec<u8>> {
    rec.get(8..8 + pixels * 3).map(<[u8]>::to_vec)
}

/// The picture's indices: `ncol` colours in the palette, `bits_for(ncol)`
/// bits each, LSB-first — the app's `gdivoom_image_bits_table` packing.
///
/// An index outside the palette is a REFUSAL, not a read past the end: the
/// native code reads whatever is there, and this decoder would rather name
/// the file than show another file's pixels.
fn palette_pixels(rec: &[u8], pixels: usize) -> Option<Vec<u8>> {
    let ncol = usize::from(u16::from_le_bytes([*rec.get(6)?, *rec.get(7)?]));
    if ncol == 0 || ncol > 256 {
        return None;
    }
    let palette = rec.get(8..8 + ncol * 3)?;
    let packed = rec.get(8 + ncol * 3..)?;
    let bpp = bits_for(ncol);
    let mask = (1u32 << bpp) - 1;
    let mut out = Vec::with_capacity(pixels * 3);
    let mut accumulator = 0u32;
    let mut held = 0u32;
    let mut pos = 0usize;
    for _ in 0..pixels {
        while held < bpp {
            let byte = *packed.get(pos)?;
            pos += 1;
            accumulator |= u32::from(byte) << held;
            held += 8;
        }
        let index = usize::try_from(accumulator & mask).ok()?;
        accumulator >>= bpp;
        held -= bpp;
        let colour = palette.get(index * 3..index * 3 + 3)?;
        out.extend_from_slice(colour);
    }
    Some(out)
}

/// Lay the decoder's flat run of 16x16 tiles into the picture they describe.
fn place_tiles(flat: &[u8], rows: usize, cols: usize) -> Option<Vec<u8>> {
    if rows == 0 || cols == 0 {
        return None;
    }
    let tiles = rows.checked_mul(cols)?;
    if flat.len() != tiles * 256 * 3 {
        return None;
    }
    let width = cols * 16;
    let mut out = vec![0u8; width * rows * 16 * 3];
    for tile in 0..tiles {
        for row in 0..16 {
            let src = (tile * 256 + row * 16) * 3;
            let dst = (((tile / cols) * 16 + row) * width + (tile % cols) * 16) * 3;
            out.get_mut(dst..dst + 48)?
                .copy_from_slice(flat.get(src..src + 48)?);
        }
    }
    Some(out)
}

/// Decode one magic-26 record into the picture it carries.
///
/// `rows` x `cols` is the container's tile grid. Returns the picture's RGB
/// bytes (row-major, `cols * 16` pixels wide) and the record's own display
/// time in milliseconds.
pub fn decode_iframe_record(rec: &[u8], rows: usize, cols: usize) -> Option<(Vec<u8>, u32)> {
    if rows == 0 || cols == 0 || rec.len() < 8 || rec[0] != 0xAA {
        return None;
    }
    let time_ms = u32::from(u16::from_le_bytes([rec[3], rec[4]]));
    let flag = rec[5] & 0x7f;
    let pixels = flag_pixels(flag)?;
    let tile_run = match flag {
        0x0B | 0x11 => raw_pixels(rec, pixels)?,
        _ => palette_pixels(rec, pixels)?,
    };
    let picture = place_tiles(&tile_run, rows, cols)?;
    Some((picture, time_ms))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn fixture(name: &str) -> Vec<u8> {
        std::fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("tests/cloud_fixtures")
                .join(name),
        )
        .expect("fixture")
    }

    /// E56: the monthly-best gallery serves magic-26 (`0x1A`) containers, and
    /// the native decoder could not read them — the run counted them as
    /// warnings and carried on without saying which. This is the gallery's
    /// own file ("Jack Skellington", fetched 2026-10-21 from the cloud's
    /// classify-18 category): a 4x4 grid of 16x16 tiles, 64x64, two frames.
    #[test]
    fn a_gallery_magic26_file_decodes() {
        let raw = fixture("gallery_magic26_jack_skellington.bin");
        let (frames, w, h, dur) = crate::art_codec::decode_cloud_magic26(&raw)
            .expect("the gallery's magic-26 file decodes");
        assert_eq!((w, h, dur, frames.len()), (64, 64, 500, 2));
        assert_eq!(frames[0].len(), 64 * 64 * 3, "a 64x64 RGB frame");
        // The picture, pinned: a SHA-1 of the first frame's RGB, so a change
        // in the palette, the bit order or the tile layout shows up here.
        assert_eq!(
            crate::art_hot::sha1_digest_hex(&frames[0]),
            "0f732027b40f68e505e8441fd8fa3b56ff6b1244"
        );
    }

    /// The container's own frame lengths add up to the file's length: the
    /// structural proof that the frames were read where the file says.
    #[test]
    fn the_frames_consume_the_whole_file() {
        let raw = fixture("gallery_magic26_jack_skellington.bin");
        let frames = usize::from(raw[1]);
        let mut pos = 6usize;
        for _ in 0..frames {
            let len =
                u32::from_be_bytes([raw[pos], raw[pos + 1], raw[pos + 2], raw[pos + 3]]) as usize;
            pos += 4 + len;
        }
        assert_eq!(pos, raw.len(), "the frames end exactly at the file's end");
    }

    /// The picture is the ART, not a scramble: the SHA-1 of the first frame
    /// is pinned against the file the cloud served.
    #[test]
    fn the_gallery_frame_decodes_to_its_picture() {
        let raw = fixture("gallery_magic26_jack_skellington.bin");
        let (picture, time_ms) =
            decode_iframe_record(&raw[10..10 + 4626], 4, 4).expect("the first frame decodes");
        assert_eq!(time_ms, 500, "the record's own display time");
        assert_eq!(picture.len(), 64 * 64 * 3);
        assert_eq!(
            crate::art_hot::sha1_digest_hex(&picture),
            "0f732027b40f68e505e8441fd8fa3b56ff6b1244"
        );
    }

    #[test]
    fn a_truncated_record_is_refused_not_half_painted() {
        let raw = fixture("gallery_magic26_jack_skellington.bin");
        assert!(decode_iframe_record(&raw[10..200], 4, 4).is_none());
        assert!(decode_iframe_record(&raw[10..10 + 4626], 4, 5).is_none());
        assert!(decode_iframe_record(&raw[10..10 + 4626], 0, 4).is_none());
    }

    /// A flag this decoder does not read is refused — the run then NAMES the
    /// file instead of showing the wrong colours.
    #[test]
    fn a_flag_this_decoder_does_not_read_is_refused() {
        let raw = fixture("gallery_magic26_jack_skellington.bin");
        let mut rec = raw[10..10 + 4626].to_vec();
        rec[5] = 0x14; // the app's "net" colour order
        assert!(decode_iframe_record(&rec, 4, 4).is_none());
    }
}
