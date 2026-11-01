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
#[must_use]
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

fn raw_rows(blob: &[u8], off: usize) -> [u16; 16] {
    let g = &blob[off..off + GLYPH_BYTES];
    let mut r = [0u16; 16];
    for i in 0..16 {
        r[i] = (u16::from(g[i * 2]) << 8) | u16::from(g[i * 2 + 1]);
    }
    r
}

/// First and last rows with ink.
fn ink_span(rows: &[u16; 16]) -> Option<(i32, i32)> {
    let lit = || (0i32..16).filter(|&i| rows[usize::try_from(i).unwrap_or(0)] != 0);
    Some((lit().next()?, lit().next_back()?))
}

const fn const_eq(a: &[u8], b: &[u8]) -> bool {
    let mut i = 0;
    while i < a.len() {
        if a[i] != b[i] {
            return false;
        }
        i += 1;
    }
    true
}

/// `a / b` rounded half up, for small non-negative-denominator integers.
const fn round_div(a: i32, b: i32) -> i32 {
    (2 * a + b).div_euclid(2 * b)
}

/// A half-size glyph moved to the band the vendor's FULL font gives it.
///
/// The half blob stores every glyph from row 0 with no baseline, so `-`, `.`,
/// `_` and short lowercase all hang from the cap line (a 16px weather frame
/// wrote -5 as an overline beside a 5). The full blob carries each glyph's
/// place; a glyph it draws over the whole cap band (digits, capitals) keeps its
/// rows, and any other is centred where the full font centres it, scaled from
/// the full cap band (`0`'s ink) onto the half one. Device-bound glyph bytes
/// (`device_glyph_bytes`) are uploaded verbatim and never pass through here.
fn half_on_band(rows: [u16; 16], off: usize) -> [u16; 16] {
    let cap = |blob: &[u8]| {
        BitmapFont::find_glyph_offset(u32::from('0')).and_then(|o| ink_span(&raw_rows(blob, o)))
    };
    let (Some((hct, hcb)), Some((fct, fcb))) = (cap(FONT_BYTES), cap(FONT_BYTES_FULL)) else {
        return rows;
    };
    let (Some((top, bottom)), Some((ft, fb))) =
        (ink_span(&rows), ink_span(&raw_rows(FONT_BYTES_FULL, off)))
    else {
        return rows;
    };
    if ft <= fct && fb >= fcb {
        return rows;
    }
    let h = bottom - top + 1;
    let centre_x2 = 2 * hct + round_div((ft + fb - 2 * fct) * (hcb - hct), fcb - fct);
    let want = round_div(centre_x2 - (h - 1), 2).clamp(0, 16 - h);
    let mut out = [0u16; 16];
    for (i, &v) in rows.iter().enumerate() {
        let i = i32::try_from(i).unwrap_or(0);
        if let Ok(j) = usize::try_from(i - top + want) {
            if j < 16 && v != 0 {
                out[j] = v;
            }
        }
    }
    out
}

pub(crate) struct BitmapFont {
    blob: &'static [u8],
    space_width: i32,
    /// The half-size blob, whose glyphs `half_on_band` places.
    half: bool,
}

/// How a line of text is drawn: its colour, the gap between glyphs, and the
/// width (from the line's own x0) past which it stops.
#[derive(Debug, Clone, Copy)]
pub(crate) struct TextStyle {
    pub color: (u8, u8, u8),
    pub gap: i32,
    pub max_width: Option<i32>,
}

impl BitmapFont {
    pub(crate) const fn new(blob: &'static [u8]) -> Self {
        Self {
            blob,
            space_width: 3,
            half: blob.len() == FONT_BYTES.len() && const_eq(blob, FONT_BYTES),
        }
    }

    pub(crate) fn find_glyph_offset(cp: u32) -> Option<usize> {
        if (FIRST_CP..=LAST_CP).contains(&cp) {
            Some(((cp - FIRST_CP) as usize) * GLYPH_BYTES)
        } else {
            None
        }
    }

    pub(crate) fn rows(&self, ch: char) -> [u16; 16] {
        let cp = ch as u32;
        let mut off = Self::find_glyph_offset(cp);
        if off.is_none() {
            off = Self::find_glyph_offset(FALLBACK_CP);
        }
        let Some(off) = off else { return [0; 16] };
        let r = raw_rows(self.blob, off);
        if self.half {
            return half_on_band(r, off);
        }
        r
    }

    pub(crate) fn col_bbox(rows: &[u16; 16]) -> Option<(usize, usize)> {
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

    pub(crate) fn char_width(&self, ch: char) -> i32 {
        if ch == ' ' {
            return self.space_width;
        }
        let rows = self.rows(ch);
        if let Some((c0, c1)) = Self::col_bbox(&rows) {
            // Column indices inside one 8-or-16-wide bitmap: tiny by construction.
            i32::try_from(c1 - c0 + 1).expect("glyph width fits i32")
        } else {
            self.space_width
        }
    }

    /// Width `draw_text` would advance for `text`, unclipped.
    ///
    /// Deliberately built from `char_width` and the same `gap` rule
    /// `draw_text` uses rather than re-deriving glyph advances: two
    /// measurements of one layout is the drift this module exists to avoid, one
    /// level down. `measure_matches_draw_text` pins them together.
    pub(crate) fn measure_width(&self, text: &str, gap: i32) -> i32 {
        text.chars()
            .enumerate()
            .map(|(i, ch)| if i > 0 { gap } else { 0 } + self.char_width(ch))
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

    /// Draw `text` with its top-left at `(x0, y0)`; returns the x after the
    /// last glyph drawn. Glyphs that would cross `style.max_width` (measured
    /// from `x0`) stop the line.
    pub(crate) fn draw_text(
        &self,
        buf: &mut [u8],
        size: i32,
        x0: i32,
        y0: i32,
        text: &str,
        style: &TextStyle,
    ) -> i32 {
        let TextStyle {
            color,
            gap,
            max_width,
        } = *style;
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
            let bb = Self::col_bbox(&rows);
            if bb.is_none() {
                x += advance + self.space_width;
                continue;
            }
            let (c0, c1) = bb.unwrap();
            let gw = i32::try_from(c1 - c0 + 1).expect("glyph width fits i32");
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
                // Row and column indices inside one cell: small by construction.
                let yy = y0 + i32::try_from(r).expect("glyph row fits i32");
                if yy < 0 || yy >= size {
                    continue;
                }
                for c in c0..=c1 {
                    if ((v >> (15 - c)) & 1) != 0 {
                        let xx = x + i32::try_from(c).expect("glyph column fits i32")
                            - i32::try_from(c0).expect("glyph column fits i32");
                        if xx >= 0 && xx < size {
                            let idx = usize::try_from((yy * size + xx) * 3)
                                .expect("clipped pixel offset");
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
