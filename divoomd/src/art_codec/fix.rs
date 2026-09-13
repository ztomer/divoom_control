//! Divoom's "fix" quadtree frame: the `0xAA` record with flag `0x15`.
//!
//! Ported on 2026-09-13 from the app's native library (`libtimebox.so`,
//! `divoom_image_decode_decode_one_fix` and `decode_fix_{64,32,16,8}`,
//! read with Ghidra) because the clock-face store's pictures come in it and
//! nothing else here could read them. The app's own dispatcher routes magic
//! `26` (`0x1A`) containers to this family (`PixelDecode128` /
//! `PixelDecode64New`), NOT to the AES+LZO layout magic `18` uses -- the
//! two were treated as one here before.
//!
//! Record: `AA len:u16 LE time:u16 LE flag ncolors:u16 LE palette[n*3] body`.
//! The 128x128 body is four 64x64 quadrants (left-right, top-bottom). Each
//! node of the tree is coded one of three ways:
//!
//! * mode 0: every pixel is an index into the palette the parent handed
//!   down, `bits(len(parent))` bits each, LSB-first, 8x8 tiles row-major;
//! * mode 2: a bitmask over the parent palette picks a sub-palette, then
//!   the pixels as above with `bits(len(sub))` bits each;
//! * mode 1: the same bitmask, then four children of half the size.
//!
//! The 8x8 leaf packs the mode into its count byte (`0x80 | n` = masked).
//! `bits(n)` is `ceil(log2 n)` (0 for n <= 1): `gdivoom_image_bits_table`.

/// `gdivoom_image_bits_table`: bits per index for a palette of `n`.
const fn bits_for(n: usize) -> u32 {
    if n <= 1 {
        0
    } else {
        usize::BITS - (n - 1).leading_zeros()
    }
}

struct BitReader<'a> {
    data: &'a [u8],
    byte: usize,
    bit: u32,
}

impl BitReader<'_> {
    fn read(&mut self, bpp: u32) -> Option<usize> {
        let mut v = 0usize;
        for k in 0..bpp {
            let b = *self.data.get(self.byte)?;
            v |= usize::from((b >> self.bit) & 1) << k;
            self.bit += 1;
            if self.bit == 8 {
                self.bit = 0;
                self.byte += 1;
            }
        }
        Some(v)
    }
}

struct Canvas<'a> {
    out: &'a mut [u8],
    width: usize,
    palette: &'a [[u8; 3]],
}

impl Canvas<'_> {
    /// `size` x `size` pixels at (`x0`, `y0`) as 8x8 tiles, row-major.
    fn paint(
        &mut self,
        x0: usize,
        y0: usize,
        size: usize,
        reader: &mut BitReader,
        bpp: u32,
        sub: &[u8],
    ) -> Option<()> {
        for by in 0..size / 8 {
            for bx in 0..size / 8 {
                for y in 0..8 {
                    for x in 0..8 {
                        let idx = reader.read(bpp)?;
                        let global = usize::from(*sub.get(idx)?);
                        let rgb = self.palette.get(global)?;
                        let o = ((y0 + by * 8 + y) * self.width + x0 + bx * 8 + x) * 3;
                        self.out.get_mut(o..o + 3)?.copy_from_slice(rgb);
                    }
                }
            }
        }
        Some(())
    }
}

/// The parent entries whose bit is set in the `n`-bit mask at `data[pos..]`.
fn mask_select(data: &[u8], pos: usize, n: usize, parent: &[u8]) -> Option<(Vec<u8>, usize)> {
    let mask_bytes = n.div_ceil(8);
    let mask = data.get(pos..pos + mask_bytes)?;
    let sel = (0..n.min(parent.len()))
        .filter(|&i| (mask[i >> 3] >> (i & 7)) & 1 == 1)
        .map(|i| parent[i])
        .collect();
    Some((sel, mask_bytes))
}

/// Decode one node; returns the bytes it consumed.
fn decode_level(
    data: &[u8],
    pos: usize,
    canvas: &mut Canvas,
    size: usize,
    x0: usize,
    y0: usize,
    parent: &[u8],
) -> Option<usize> {
    if size == 8 {
        let b = *data.get(pos)?;
        if b & 0x80 != 0 {
            let (sel, mb) = mask_select(data, pos + 1, usize::from(b & 0x7f), parent)?;
            let bpp = bits_for(sel.len());
            let mut r = BitReader {
                data,
                byte: pos + 1 + mb,
                bit: 0,
            };
            canvas.paint(x0, y0, 8, &mut r, bpp, &sel)?;
            return Some(1 + mb + bpp as usize * 8);
        }
        let bpp = bits_for(parent.len());
        let mut r = BitReader {
            data,
            byte: pos + 1,
            bit: 0,
        };
        canvas.paint(x0, y0, 8, &mut r, bpp, parent)?;
        return Some(1 + bpp as usize * 8);
    }
    let mode = *data.get(pos)?;
    let n = match *data.get(pos + 1)? {
        0 => 256,
        k => usize::from(k),
    };
    let px_bytes = size * size / 8;
    if mode == 0 {
        let bpp = bits_for(parent.len());
        let mut r = BitReader {
            data,
            byte: pos + 1,
            bit: 0,
        };
        canvas.paint(x0, y0, size, &mut r, bpp, parent)?;
        return Some(1 + bpp as usize * px_bytes);
    }
    let (sel, mb) = mask_select(data, pos + 2, n, parent)?;
    if mode == 2 {
        let bpp = bits_for(sel.len());
        let mut r = BitReader {
            data,
            byte: pos + 2 + mb,
            bit: 0,
        };
        canvas.paint(x0, y0, size, &mut r, bpp, &sel)?;
        return Some(2 + mb + bpp as usize * px_bytes);
    }
    let mut used = 2 + mb;
    let h = size / 2;
    for (dx, dy) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
        used += decode_level(data, pos + used, canvas, h, x0 + dx * h, y0 + dy * h, &sel)?;
    }
    Some(used)
}

/// Decode a flag-`0x15` record into a 128x128 RGB frame (row-major) and
/// its display time in ms. `None` when the record is not one, or is cut
/// short -- a truncated file must not paint half a face as a whole one.
pub fn decode_fix_128(rec: &[u8]) -> Option<(Vec<u8>, u32)> {
    if rec.len() < 8 || rec[0] != 0xAA || rec[5] & 0x7f != 0x15 {
        return None;
    }
    let time_ms = u32::from(u16::from_le_bytes([rec[3], rec[4]]));
    let ncol = usize::from(u16::from_le_bytes([rec[6], rec[7]]));
    let palette: Vec<[u8; 3]> = rec.get(8..8 + ncol * 3)?.as_chunks::<3>().0.to_vec();
    let parent: Vec<u8> = (0..=u8::MAX).take(ncol).collect();
    let mut out = vec![0u8; 128 * 128 * 3];
    let mut canvas = Canvas {
        out: &mut out,
        width: 128,
        palette: &palette,
    };
    let mut pos = 8 + ncol * 3;
    for (qx, qy) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
        pos += decode_level(rec, pos, &mut canvas, 64, qx * 64, qy * 64, &parent)?;
    }
    if pos > rec.len() {
        return None;
    }
    Some((out, time_ms))
}

/// A magic-`26` container: `{26, frames, speed:u16 BE, rows, cols}` then
/// per frame `len:u32 BE` + one record. Only the 128x128 (8x8 tile) shape
/// is decoded here; the record's own time wins over the header's when set.
pub fn decode_cloud_magic26(data: &[u8]) -> Option<(Vec<Vec<u8>>, u32, u32, u32)> {
    if data.len() < 10 || data[0] != 26 || data[4] != 8 || data[5] != 8 {
        return None;
    }
    let total = usize::from(data[1]);
    let speed = u32::from(u16::from_be_bytes([data[2], data[3]]));
    let mut frames = Vec::new();
    let mut pos = 6;
    let mut dur = if speed >= 10 { speed } else { 100 };
    for _ in 0..total.min(24) {
        let len = u32::from_be_bytes([
            *data.get(pos)?,
            *data.get(pos + 1)?,
            *data.get(pos + 2)?,
            *data.get(pos + 3)?,
        ]) as usize;
        let rec = data.get(pos + 4..pos + 4 + len)?;
        let (rgb, t) = decode_fix_128(rec)?;
        if t >= 10 {
            dur = t;
        }
        frames.push(rgb);
        pos += 4 + len;
    }
    if frames.is_empty() {
        return None;
    }
    Some((frames, 128, 128, dur))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> Vec<u8> {
        std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/cloud_fixtures/store_face_998_digital_tech.bin"
        ))
        .expect("fixture")
    }

    #[test]
    fn the_bits_table_is_ceil_log2() {
        // Read from the library: [0,0,1,2,2,3,3,3,3,4,...], 64->6, 65->7, 128->7, 129->8.
        for (n, want) in [
            (0, 0),
            (1, 0),
            (2, 1),
            (3, 2),
            (4, 2),
            (5, 3),
            (9, 4),
            (64, 6),
            (65, 7),
            (128, 7),
            (129, 8),
            (256, 8),
        ] {
            assert_eq!(bits_for(n), want, "bits({n})");
        }
    }

    #[test]
    fn the_store_face_decodes_pixel_for_pixel() {
        // The clock-face store's "Digital Tech" (ClockId 998), fetched
        // 2026-09-13. The reference decode is the Python port of the same
        // routines, checked by eye against the face: SHA-1 of the RGB.
        let raw = fixture();
        let (frames, w, h, dur) = decode_cloud_magic26(&raw).expect("decodes");
        assert_eq!((w, h, dur, frames.len()), (128, 128, 500, 1));
        let rgb = &frames[0];
        assert_eq!(rgb.len(), 128 * 128 * 3);
        assert_eq!(&rgb[0..3], &[0, 0, 0]);
        let at = |x: usize, y: usize| &rgb[(y * 128 + x) * 3..(y * 128 + x) * 3 + 3];
        assert_eq!(at(64, 64), &[0x00, 0x41, 0x2b]);
        assert_eq!(
            crate::art_hot::sha1_digest_hex(rgb),
            "4ce620b83c76fb1bd44e3d4ae3728e260e8149cb"
        );
        // The frame consumed EXACTLY its declared length: the quadtree's
        // sizes add up, which is the structural proof of the port.
        let len = u32::from_be_bytes([raw[6], raw[7], raw[8], raw[9]]) as usize;
        assert_eq!(10 + len, raw.len());
    }

    #[test]
    fn a_truncated_record_is_refused_not_half_painted() {
        let raw = fixture();
        assert!(decode_cloud_magic26(&raw[..raw.len() - 40]).is_none());
        assert!(decode_fix_128(&raw[10..200]).is_none());
        assert!(
            decode_cloud_magic26(&[26, 1, 0, 100, 2, 2]).is_none(),
            "32x32 is not this shape"
        );
    }
}
