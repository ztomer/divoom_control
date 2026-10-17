//! The weather widget as a frame we draw (P3.3).
//!
//! `push_weather` used to configure the panel's OWN clock face -- a
//! `ClockPacket` with the weather panel switched on, then the 0x5F temperature
//! and icon -- and so inherited the firmware's semantics: the face cycles
//! clock -> temperature on its own, its look differs per model, and the 0x5F
//! data lands on whatever face the device happens to show. That is why weather
//! was the one widget that broke. Every other widget renders frames; weather
//! now does too, through the same `render_widget` call its preview uses.
//!
//! The icons are hand-drawn on a 12x8 grid and scaled by WHOLE multiples only
//! (16 -> x1, 32 -> x2, 64 -> x4): integer upscaling keeps pixel art exact,
//! where any fractional resample would blur it. Each condition is a different
//! SHAPE (disc, cloud, cloud+drops, cloud+flakes, cloud+bolt, bars), so the
//! icons stay distinguishable with the colour taken away -- the house rule that
//! colour reinforces and shape carries, pinned by a greyscale test.

use super::font::{BitmapFont, TextStyle, CELL, FONT_BYTES, FONT_BYTES_FULL};
use crate::packets::WeatherType;

const BG: (u8, u8, u8) = (5, 6, 12);
const TEXT: (u8, u8, u8) = (235, 235, 235);
const ICON_W: i32 = 12;
const ICON_H: i32 = 8;

/// One icon, row by row; each letter is a palette entry, `.` is background.
const fn icon(weather: WeatherType) -> [&'static str; 8] {
    match weather {
        WeatherType::Clear => [
            "....Y..Y....",
            ".Y..YYYY..Y.",
            "...YYYYYY...",
            "..YYYYYYYY..",
            "..YYYYYYYY..",
            "...YYYYYY...",
            ".Y..YYYY..Y.",
            "....Y..Y....",
        ],
        WeatherType::CloudySky => [
            "............",
            ".....WWW....",
            "...WWWWWW...",
            "..WWWWWWWWW.",
            ".WWWWWWWWWWW",
            ".WWWWWWWWWWW",
            "..WWWWWWWWW.",
            "............",
        ],
        WeatherType::Rain => [
            "....WWW.....",
            "..WWWWWWW...",
            ".WWWWWWWWWW.",
            ".WWWWWWWWWW.",
            "............",
            "..B..B..B...",
            ".B..B..B....",
            "............",
        ],
        WeatherType::Snow => [
            "....WWW.....",
            "..WWWWWWW...",
            ".WWWWWWWWWW.",
            ".WWWWWWWWWW.",
            "............",
            "..S...S...S.",
            "....S...S...",
            "..S...S...S.",
        ],
        WeatherType::Thunderstorm => [
            "....GGG.....",
            "..GGGGGGG...",
            ".GGGGGGGGGG.",
            ".GGGGLGGGGG.",
            ".....LL.....",
            "....LL......",
            ".....L......",
            "............",
        ],
        WeatherType::Fog => [
            "............",
            ".FFFFFFFFFF.",
            "............",
            "..FFFFFFFFFF",
            "............",
            ".FFFFFFFFFF.",
            "............",
            "..FFFFFFFF..",
        ],
    }
}

const fn palette(c: u8) -> Option<(u8, u8, u8)> {
    match c {
        b'Y' => Some((255, 200, 0)),
        b'W' => Some((220, 225, 235)),
        b'G' => Some((120, 125, 140)),
        b'B' => Some((60, 150, 255)),
        b'S' => Some((255, 255, 255)),
        b'L' => Some((255, 220, 0)),
        b'F' => Some((150, 155, 165)),
        _ => None,
    }
}

/// A square RGB canvas with clipped, integer-scaled drawing.
struct Canvas {
    edge: i32,
    buf: Vec<u8>,
}

impl Canvas {
    fn new(size: u32) -> Self {
        let edge = i32::try_from(size).expect("panel edge fits i32");
        let px = usize::try_from(size * size).expect("panel pixels fit usize");
        Self {
            edge,
            buf: <[u8; 3]>::from(BG).repeat(px),
        }
    }

    /// Fill the `scale`x`scale` block whose top-left is `(left, top)`, clipped.
    fn block(&mut self, left: i32, top: i32, scale: i32, rgb: (u8, u8, u8)) {
        for row in top.max(0)..(top + scale).min(self.edge) {
            for col in left.max(0)..(left + scale).min(self.edge) {
                let at = usize::try_from((row * self.edge + col) * 3).expect("clipped offset");
                self.buf[at..at + 3].copy_from_slice(&<[u8; 3]>::from(rgb));
            }
        }
    }
}

/// How wide a degree mark a reading `w` glyph-pixels wide can carry at scale
/// `k` on an `edge`-pixel panel: the full `deg`, none (`Some(0)`) when only
/// the digits fit, or `None` when even they would be clipped.
const fn degree_mark(w: i32, deg: i32, k: i32, edge: i32) -> Option<i32> {
    if (w + 1 + deg) * k <= edge {
        Some(deg)
    } else if w * k <= edge {
        Some(0)
    } else {
        None
    }
}

/// `temp_c`, scaled by `k`, centred in rows `top..bottom` -- with its degree
/// mark when that fits, without it when only the digits do, and not at all
/// when even they would be clipped: a cut-off "-1" for -12 is a wrong
/// reading, which is worse than none. Returns whether anything was drawn.
fn draw_temperature(
    canvas: &mut Canvas,
    temp_c: i8,
    full: bool,
    k: i32,
    top: i32,
    bottom: i32,
) -> bool {
    let font = BitmapFont::new(if full { FONT_BYTES_FULL } else { FONT_BYTES });
    let text = temp_c.to_string();
    let w = font.measure_width(&text, 1);
    let Some((ink_top, ink_bottom)) = font.ink_rows(&text) else {
        return false;
    };
    // The degree mark: a 2x2 block on the half font, a 3x3 ring on the full.
    let Some(deg) = degree_mark(w, if full { 3 } else { 2 }, k, canvas.edge) else {
        return false;
    };
    // Draw at native size into a scratch square, then copy lit pixels scaled.
    let cell = i32::try_from(CELL).expect("cell fits i32");
    let scratch_edge = w.max(cell);
    let mut scratch = vec![0u8; usize::try_from(scratch_edge * scratch_edge * 3).expect("scratch")];
    let style = TextStyle {
        color: TEXT,
        gap: 1,
        max_width: None,
    };
    font.draw_text(&mut scratch, scratch_edge, 0, 0, &text, &style);

    let ink_top = i32::try_from(ink_top).expect("ink row fits i32");
    let ink_h = i32::try_from(ink_bottom).expect("ink row fits i32") - ink_top + 1;
    let total_w = if deg == 0 { w } else { w + 1 + deg } * k;
    let x0 = ((canvas.edge - total_w) / 2).max(0);
    let y0 = top + ((bottom - top) - ink_h * k).max(0) / 2;
    for sy in ink_top..ink_top + ink_h {
        for sx in 0..w {
            let i = usize::try_from((sy * scratch_edge + sx) * 3).expect("scratch offset");
            if scratch[i] != 0 {
                canvas.block(x0 + sx * k, y0 + (sy - ink_top) * k, k, TEXT);
            }
        }
    }
    let dx = x0 + (w + 1) * k;
    for gy in 0..deg {
        for gx in 0..deg {
            let hollow = full && gx == 1 && gy == 1;
            if !hollow {
                canvas.block(dx + gx * k, y0 + gy * k, k, TEXT);
            }
        }
    }
    true
}

/// The weather frame for one reading at a `size`x`size` panel, raw RGB.
///
/// From 16 up: the icon across the top, the temperature centred beneath it.
/// Below 16 (a preview size; no panel is that small) there is room for one:
/// the temperature when its digits fit unclipped, else the icon.
#[must_use]
pub fn render_weather(temp_c: i8, weather: WeatherType, size: u32) -> Vec<u8> {
    let mut canvas = Canvas::new(size);
    let edge = canvas.edge;
    if size < 16 && draw_temperature(&mut canvas, temp_c, false, 1, 0, edge) {
        return canvas.buf;
    }
    let k = (edge / 16).max(1);
    let ox = (edge - ICON_W * k) / 2;
    let oy = k;
    for (row, line) in (0..).zip(icon(weather)) {
        for (col, b) in (0..).zip(line.bytes()) {
            if let Some(c) = palette(b) {
                canvas.block(ox + col * k, oy + row * k, k, c);
            }
        }
    }
    if size < 16 {
        return canvas.buf;
    }
    let text_top = oy + ICON_H * k + k / 2;
    // Full-size glyphs from 32 up, doubled again at 64, so the reading keeps
    // pace with the icon rather than shrinking into a corner.
    let (full, tk) = if size >= 32 {
        (true, (edge / 32).max(1))
    } else {
        (false, 1)
    };
    draw_temperature(&mut canvas, temp_c, full, tk, text_top, edge);
    canvas.buf
}

#[cfg(test)]
#[path = "weather_frame_tests.rs"]
mod tests;
