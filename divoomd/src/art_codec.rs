//! Cloud-format codecs for art.rs: AES-CBC, magic-43/9/18/26/0xAA decoders,
//! image rescaling, SHA-1 hash. These are pure functions; split from
//! art.rs to keep both files under the 500-LOC ground rule.

use minilzo_rs::LZO;

mod aes;
pub(crate) use aes::aes_cbc_decrypt;
// ── payload decoders (ported from divoom_lib/media_decoder.py) ────────────

/// True if `d` begins with a GIF/PNG/JPG file signature.
pub(crate) fn is_image_header(d: &[u8]) -> bool {
    d.starts_with(b"GIF89a")
        || d.starts_with(b"GIF87a")
        || d.starts_with(b"\x89PNG\r\n\x1a\n")
        || d.starts_with(b"\xff\xd8")
}

/// Resolve a downloaded cloud payload to a SINGLE displayable image-file
/// (GIF/PNG/JPG) the `image` crate can decode — the image-only subset used by
/// callers that need one static file. GIF/PNG/JPG pass through; magic-43 is
/// unwrapped to its embedded image.
///
/// The full cloud/hot container handling (magic 9/18/26 → AES/LZO frames, 0xAA
/// hot → palette-delta frames, all re-encoded to an animated GIF) lives in
/// `media::resolve_to_gif`, which is what `sync_artwork` / `get_animated_preview`
/// use. This function returns None for animated containers by design.
pub(crate) fn resolve_to_image_bytes(data: &[u8]) -> Option<Vec<u8>> {
    if data.len() < 4 {
        return None;
    }
    if is_image_header(data) {
        return Some(data.to_vec());
    }
    if data[0] == 43 {
        let inner = decode_magic43(data)?;
        if is_image_header(&inner) {
            return Some(inner);
        }
    }
    None
}

/// Decode a "magic 43" cloud container — returns the embedded GIF/PNG/JPG bytes.
pub(crate) fn decode_magic43(data: &[u8]) -> Option<Vec<u8>> {
    if data.len() < 10 || data[0] != 43 {
        return None;
    }
    let text_len = u32::from_le_bytes(data[6..10].try_into().ok()?) as usize;
    let img_len_off = 10 + text_len;
    if data.len() < img_len_off + 4 {
        return None;
    }
    let img_len = u32::from_le_bytes(data[img_len_off..img_len_off + 4].try_into().ok()?) as usize;
    let img_start = img_len_off + 4;
    let img_end = (img_start + img_len).min(data.len());
    Some(data[img_start..img_end].to_vec())
}

/// Decode a cloud container (magic 9 → AES-CBC 16x16 RGB) into raw 768-byte frames.
/// Returns (frames, duration_ms). Magic 18/26 (AES + LZO) are handled by
/// `decode_cloud_magic18_26` (the LZO dependency is `minilzo_rs`).
pub(crate) fn decode_cloud_magic9(data: &[u8]) -> Option<(Vec<Vec<u8>>, u32)> {
    if data.len() < 5 || data[0] != 9 {
        return None;
    }
    let total_frames = data[1] as usize;
    let speed = u16::from_be_bytes([data[2], data[3]]) as u32;
    let decrypted = aes_cbc_decrypt(&data[4..])?;
    let mut frames = Vec::new();
    for i in 0..total_frames.min(24) {
        let start = i * 768;
        let end = start + 768;
        if end > decrypted.len() {
            break;
        }
        frames.push(decrypted[start..end].to_vec());
    }
    Some((frames, if speed >= 10 { speed } else { 100 }))
}

/// Decode a magic 18/26 cloud container: header `>BHBB`
/// `[magic][total_frames][speed:2 BE][row_count][column_count]`, then AES-CBC over
/// the rest, then per frame `[size:4 BE]` + LZO1X-compressed payload that inflates
/// to `row*col*768` bytes, reassembled via `compact_tiles`. Returns
/// `(frames, width, height, duration_ms)` — each frame is `width*height*3` RGB.
/// Mirrors Python `media_decoder.decode_cloud_frames` (magic 18/26).
pub(crate) fn decode_cloud_magic18_26(data: &[u8]) -> Option<(Vec<Vec<u8>>, u32, u32, u32)> {
    if data.len() < 6 {
        return None;
    }
    let magic = data[0];
    if magic != 18 && magic != 26 {
        return None;
    }
    let total_frames = data[1] as usize;
    let speed = u16::from_be_bytes([data[2], data[3]]) as u32;
    let row_count = data[4] as usize;
    let column_count = data[5] as usize;
    if row_count == 0 || column_count == 0 {
        return None;
    }
    let decrypted = aes_cbc_decrypt(&data[6..])?;
    let uncompressed = row_count * column_count * 768;
    let lzo = LZO::init().ok()?;
    let mut frames = Vec::new();
    let mut pos = 0usize;
    for _ in 0..total_frames.min(24) {
        if pos + 4 > decrypted.len() {
            break;
        }
        let frame_size = u32::from_be_bytes([
            decrypted[pos],
            decrypted[pos + 1],
            decrypted[pos + 2],
            decrypted[pos + 3],
        ]) as usize;
        pos += 4;
        if pos + frame_size > decrypted.len() {
            break;
        }
        let compressed = &decrypted[pos..pos + frame_size];
        pos += frame_size;
        let raw = lzo.decompress_safe(compressed, uncompressed).ok()?;
        frames.push(compact_tiles(&raw, row_count, column_count));
    }
    if frames.is_empty() {
        return None;
    }
    let width = (column_count * 16) as u32;
    let height = (row_count * 16) as u32;
    Some((frames, width, height, if speed >= 10 { speed } else { 100 }))
}

/// Reassemble `row_count×column_count` 16×16 tiles (concatenated in grid order,
/// each tile row-major RGB) into one `(col*16)×(row*16)` RGB frame. Pure-Python
/// `_compact_tiles` fallback ported byte-for-byte.
fn compact_tiles(data: &[u8], row_count: usize, column_count: usize) -> Vec<u8> {
    let width = column_count * 16;
    let height = row_count * 16;
    let mut out = vec![0u8; width * height * 3];
    let mut pos = 0usize;
    for grid_y in 0..row_count {
        for grid_x in 0..column_count {
            for y in 0..16 {
                for x in 0..16 {
                    if pos + 3 <= data.len() {
                        let px = grid_x * 16 + x;
                        let py = grid_y * 16 + y;
                        let oidx = (py * width + px) * 3;
                        out[oidx] = data[pos];
                        out[oidx + 1] = data[pos + 1];
                        out[oidx + 2] = data[pos + 2];
                        pos += 3;
                    }
                }
            }
        }
    }
    out
}

/// Decode a 0xAA hot-file format into raw 768-byte RGB frames.
pub(crate) fn decode_hot_file(data: &[u8]) -> Option<Vec<(Vec<u8>, u32)>> {
    if data.len() < 7 || data[0] != 0xAA {
        return None;
    }
    let mut frames: Vec<(Vec<u8>, u32)> = Vec::new();
    let mut palette: Vec<[u8; 3]> = Vec::new();
    let mut off = 0usize;
    while off + 7 <= data.len() && frames.len() < 60 {
        if data[off] != 0xAA {
            break;
        }
        let frame_len = u16::from_le_bytes([data[off + 1], data[off + 2]]) as usize;
        let duration = u16::from_le_bytes([data[off + 3], data[off + 4]]) as u32;
        let flag = data[off + 5];
        let n_colors_raw = data[off + 6] as usize;
        if frame_len < 7 || off + frame_len > data.len() {
            break;
        }
        let mut pos = off + 7;
        if flag == 0 {
            palette.clear();
            let n = if n_colors_raw == 0 { 256 } else { n_colors_raw };
            if pos + n * 3 > data.len() {
                break;
            }
            for _ in 0..n {
                palette.push([data[pos], data[pos + 1], data[pos + 2]]);
                pos += 3;
            }
        } else {
            if pos + n_colors_raw * 3 > data.len() {
                break;
            }
            for _ in 0..n_colors_raw {
                palette.push([data[pos], data[pos + 1], data[pos + 2]]);
                pos += 3;
            }
        }
        if palette.is_empty() {
            break;
        }
        // bits-per-pixel = (palette_len - 1).bit_length() — ceil(log2) of the index
        // space. (The old next_power_of_two().trailing_zeros() under-counted for
        // non-power-of-two palette sizes, e.g. len 3 gave 1 instead of 2.)
        let bpp = {
            let x = palette.len() - 1;
            if x == 0 {
                0
            } else {
                (usize::BITS - x.leading_zeros()) as usize
            }
        };
        let indices: Vec<usize> = if bpp == 0 {
            vec![0usize; 256]
        } else {
            let n_bytes = (256 * bpp).div_ceil(8);
            if pos + n_bytes > data.len() {
                break;
            }
            let packed = data[pos..pos + n_bytes]
                .iter()
                .enumerate()
                .fold(0u128, |a, (i, &b)| a | ((b as u128) << (i * 8)));
            let mask = (1usize << bpp) - 1;
            (0..256)
                .map(|i| (packed >> (i * bpp)) as usize & mask)
                .collect()
        };
        if indices.iter().any(|&i| i >= palette.len()) {
            return None;
        }
        let rgb: Vec<u8> = indices
            .iter()
            .flat_map(|&i| palette[i].iter().copied())
            .collect();
        frames.push((rgb, if duration > 0 { duration } else { 100 }));
        off += frame_len;
    }
    if frames.is_empty() {
        None
    } else {
        Some(frames)
    }
}

// ── encode one animation frame body using the C dylib ────────────────────

#[cfg(test)]
mod parity_tests {
    //! Byte-for-byte parity against the Python `media_decoder` oracle. Fixtures in
    //! `tests/cloud_fixtures/` are real cloud files + their Python-decoded frames
    //! (see the fixture generator in the round notes). These prove the Rust cloud
    //! decoders match Python BEFORE anything is pushed to a device.
    use super::*;
    use std::path::PathBuf;

    fn fpath(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/cloud_fixtures")
            .join(name)
    }
    fn raw(name: &str) -> Vec<u8> {
        std::fs::read(fpath(name)).expect("fixture .bin")
    }
    fn oracle(name: &str) -> serde_json::Value {
        serde_json::from_slice(&std::fs::read(fpath(name)).expect("fixture .json")).expect("json")
    }
    fn unhex(s: &str) -> Vec<u8> {
        (0..s.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
            .collect()
    }

    #[test]
    fn magic9_matches_python_oracle() {
        let (frames, dur) = decode_cloud_magic9(&raw("magic9.bin")).expect("magic9 decode");
        let o = oracle("magic9.json");
        let exp = o["frames"].as_array().unwrap();
        assert_eq!(dur, o["dur"].as_u64().unwrap() as u32, "duration");
        assert_eq!(frames.len(), exp.len(), "frame count");
        for (i, (got, e)) in frames.iter().zip(exp).enumerate() {
            assert_eq!(
                *got,
                unhex(e.as_str().unwrap()),
                "magic9 frame {i} bytes differ from Python"
            );
        }
    }

    #[test]
    fn magic18_matches_python_oracle() {
        let (frames, w, h, dur) =
            decode_cloud_magic18_26(&raw("magic18.bin")).expect("magic18 decode");
        let o = oracle("magic18.json");
        let size = o["size"].as_array().unwrap();
        assert_eq!(w, size[0].as_u64().unwrap() as u32, "width");
        assert_eq!(h, size[1].as_u64().unwrap() as u32, "height");
        assert_eq!(dur, o["dur"].as_u64().unwrap() as u32, "duration");
        let exp = o["frames"].as_array().unwrap();
        assert_eq!(frames.len(), exp.len(), "frame count");
        for (i, (got, e)) in frames.iter().zip(exp).enumerate() {
            assert_eq!(
                *got,
                unhex(e.as_str().unwrap()),
                "magic18 frame {i} bytes differ from Python"
            );
        }
    }
}
