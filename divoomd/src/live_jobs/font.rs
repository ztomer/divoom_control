//! The embedded bitmap font: glyph lookup, metrics and text layout.
//!
//! Split out of `render.rs` in R73, when adding `device_glyph_bytes` pushed
//! that file past the repo's 500-line cap. The font is a self-contained
//! subject with two distinct consumers -- the pixel renderers here, and
//! device-bound scrolling text, which uploads these same 32-byte glyphs to a
//! panel that has no font of its own.

// --- Bitmap Font ---

pub(crate) const FIRST_CP: u32 = 0x20;
pub(crate) const LAST_CP: u32 = 0x7E;
pub(crate) const GLYPH_BYTES: usize = 32;
pub(crate) const CELL: usize = 16;
pub(crate) const FALLBACK_CP: u32 = 0x3F; // '?'

pub(crate) const FONT_BYTES: &[u8] =
    include_bytes!("../../../divoom_lib/fonts/divoom_fond16_default_half.bin");

/// The full-size (~9px) glyphs. The half-size set above is what device-bound
/// text uses at 16/32px — at that scale the full glyphs fill the screen — but
/// `push_text` offers the larger one for bigger matrices, so both blobs have to
/// be here for the daemon to answer the same question the GUI used to.
pub(crate) const FONT_BYTES_FULL: &[u8] =
    include_bytes!("../../../divoom_lib/fonts/divoom_fond16_default_ascii.bin");

/// The raw 32-byte glyph for `cp`, exactly as the font blob stores it.
///
/// R73: the device has NO font of its own — the APK uploads glyph bitmaps for
/// each character of a scrolling string (`SPP_LED_UPDATE_FONT_INFO`, 0x7C)
/// before sending the string itself. `CmdManager` copies 32 bytes per glyph
/// straight out of the same `divoom_fond16_*` blob family this file already
/// embeds, so device-bound text reuses these bytes verbatim rather than
/// re-rasterising.
///
/// Falls back to '?' for anything outside the blob's ASCII range, matching
/// `BitmapFont::rows`. Returns None only if even the fallback is missing.
pub fn device_glyph_bytes(cp: u32) -> Option<&'static [u8]> {
    let off = |c: u32| -> Option<usize> {
        if (FIRST_CP..=LAST_CP).contains(&c) {
            Some(((c - FIRST_CP) as usize) * GLYPH_BYTES)
        } else {
            None
        }
    };
    let o = off(cp).or_else(|| off(FALLBACK_CP))?;
    FONT_BYTES.get(o..o + GLYPH_BYTES)
}

pub(crate) struct BitmapFont {
    blob: &'static [u8],
    space_width: i32,
}

impl BitmapFont {
    pub(crate) fn new(blob: &'static [u8]) -> Self {
        Self {
            blob,
            space_width: 3,
        }
    }

    pub(crate) fn find_glyph_offset(&self, cp: u32) -> Option<usize> {
        if (FIRST_CP..=LAST_CP).contains(&cp) {
            Some(((cp - FIRST_CP) as usize) * GLYPH_BYTES)
        } else {
            None
        }
    }

    pub(crate) fn rows(&self, ch: char) -> [u16; 16] {
        let cp = ch as u32;
        let mut off = self.find_glyph_offset(cp);
        if off.is_none() {
            off = self.find_glyph_offset(FALLBACK_CP);
        }
        let off = match off {
            Some(o) => o,
            None => return [0; 16],
        };
        let g = &self.blob[off..off + GLYPH_BYTES];
        let mut r = [0u16; 16];
        for i in 0..16 {
            r[i] = ((g[i * 2] as u16) << 8) | (g[i * 2 + 1] as u16);
        }
        r
    }

    pub(crate) fn col_bbox(&self, rows: &[u16; 16]) -> Option<(usize, usize)> {
        let mut min_col = None;
        let mut max_col = None;
        for x in 0..CELL {
            let mask = 1 << (15 - x);
            let mut occupied = false;
            for &row in rows {
                if (row & mask) != 0 {
                    occupied = true;
                    break;
                }
            }
            if occupied {
                if min_col.is_none() {
                    min_col = Some(x);
                }
                max_col = Some(x);
            }
        }
        match (min_col, max_col) {
            (Some(min), Some(max)) => Some((min, max)),
            _ => None,
        }
    }

    pub(crate) fn _char_width(&self, ch: char) -> i32 {
        if ch == ' ' {
            return self.space_width;
        }
        let rows = self.rows(ch);
        if let Some((c0, c1)) = self.col_bbox(&rows) {
            (c1 - c0 + 1) as i32
        } else {
            self.space_width
        }
    }

    /// Width `draw_text` would advance for `text`, unclipped.
    ///
    /// Deliberately built from `_char_width` and the same `gap` rule
    /// `draw_text` uses rather than re-deriving glyph advances: two
    /// measurements of one layout is the drift this module exists to avoid, one
    /// level down. `measure_matches_draw_text` pins them together.
    pub(crate) fn measure_width(&self, text: &str, gap: i32) -> i32 {
        text.chars()
            .enumerate()
            .map(|(i, ch)| if i > 0 { gap } else { 0 } + self._char_width(ch))
            .sum()
    }

    /// Topmost and bottommost glyph rows that have ink, or `None` for blank
    /// text. Used to centre vertically: the half-size glyphs sit in the top of
    /// a 16-row cell, so drawing at y=0 hangs text off the top edge.
    pub(crate) fn ink_rows(&self, text: &str) -> Option<(usize, usize)> {
        let mut top: Option<usize> = None;
        let mut bottom: Option<usize> = None;
        for ch in text.chars() {
            if ch == ' ' {
                continue;
            }
            for (r, &v) in self.rows(ch).iter().enumerate().take(CELL) {
                if v != 0 {
                    if top.is_none_or(|t| r < t) {
                        top = Some(r);
                    }
                    if bottom.is_none_or(|b| r > b) {
                        bottom = Some(r);
                    }
                }
            }
        }
        match (top, bottom) {
            (Some(t), Some(b)) => Some((t, b)),
            _ => None,
        }
    }

    #[expect(clippy::too_many_arguments)]
    pub(crate) fn draw_text(
        &self,
        buf: &mut [u8],
        size: i32,
        x0: i32,
        y0: i32,
        text: &str,
        color: (u8, u8, u8),
        gap: i32,
        max_width: Option<i32>,
    ) -> i32 {
        let mut x = x0;
        let chars: Vec<char> = text.chars().collect();
        for (i, &ch) in chars.iter().enumerate() {
            let advance = if i > 0 { gap } else { 0 };
            if ch == ' ' {
                if let Some(mw) = max_width {
                    if (x + advance + self.space_width - x0) > mw {
                        break;
                    }
                }
                x += advance + self.space_width;
                continue;
            }
            let rows = self.rows(ch);
            let bb = self.col_bbox(&rows);
            if bb.is_none() {
                x += advance + self.space_width;
                continue;
            }
            let (c0, c1) = bb.unwrap();
            let gw = (c1 - c0 + 1) as i32;
            if let Some(mw) = max_width {
                if (x + advance + gw - x0) > mw {
                    break;
                }
            }
            x += advance;
            for (r, &v) in rows.iter().take(CELL).enumerate() {
                if v == 0 {
                    continue;
                }
                let yy = y0 + r as i32;
                if yy < 0 || yy >= size {
                    continue;
                }
                for c in c0..=c1 {
                    if ((v >> (15 - c)) & 1) != 0 {
                        let xx = x + (c as i32 - c0 as i32);
                        if xx >= 0 && xx < size {
                            let idx = ((yy * size + xx) * 3) as usize;
                            buf[idx] = color.0;
                            buf[idx + 1] = color.1;
                            buf[idx + 2] = color.2;
                        }
                    }
                }
            }
            x += gw;
        }
        x - x0
    }
}
