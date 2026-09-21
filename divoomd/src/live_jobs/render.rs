//! Pixel renderers for live-widget jobs: sysmon/stock frames, plus the macOS
//! battery probe. Pure compute (no I/O beyond `pmset`). The bitmap font lives
//! in `font.rs`.

pub use super::font::*;

/// `round(k * size / b)` for non-negative panel geometry, saturating into `i32`.
///
/// Several renderers used to compute this as `(k as f32 * scale).round() as
/// i32`, which needs a float-to-int cast. The integer form is exact for
/// non-negative inputs (the multiply runs in `u64`, so no input overflows),
/// and saturates (like the cast did) past `i32::MAX`.
fn scale_round_i32(k: u32, size: u32, b: u32) -> i32 {
    i32::try_from((u64::from(k) * u64::from(size) + u64::from(b) / 2) / u64::from(b))
        .unwrap_or(i32::MAX)
}

// --- Renderers ---

pub(crate) fn render_sysmon(cpu: u8, mem: u8, battery: u8, size: u32) -> Vec<u8> {
    // Panel edges are 16/32/64: small and never negative. The drawing code
    // below works in `i32` (coordinates go negative when clipping), so the
    // edge crosses the boundary once, here.
    let edge = i32::try_from(size).expect("panel edge is non-negative");
    let mut buf = vec![0u8; usize::try_from(size * size * 3).expect("panel buffer fits usize")];
    for i in 0..usize::try_from(size * size).expect("panel pixels fit usize") {
        buf[i * 3] = 5;
        buf[i * 3 + 1] = 6;
        buf[i * 3 + 2] = 12;
    }

    let cpu_color = (255, 200, 0);
    let mem_color = (90, 170, 255);
    let bat_color = (255, 60, 60);

    let draw_gauge =
        |buf: &mut [u8], x: i32, y: i32, w_max: i32, h: i32, val: u8, color: (u8, u8, u8)| {
            // Filled pixels for a 0..=100 value over a `w_max`-wide bar,
            // at least one so a zero reading still shows its slot.
            let w_fill = ((w_max * i32::from(val) + 50) / 100).clamp(1, w_max);
            for yy in y..y + h {
                if yy >= 0 && yy < edge {
                    for xx in x..x + w_fill {
                        if xx >= 0 && xx < edge {
                            let idx = usize::try_from((yy * edge + xx) * 3)
                                .expect("clipped pixel offset");
                            buf[idx] = color.0;
                            buf[idx + 1] = color.1;
                            buf[idx + 2] = color.2;
                        }
                    }
                }
            }
        };

    if size <= 16 {
        draw_gauge(&mut buf, 1, 1, 14, 3, cpu, cpu_color);
        draw_gauge(&mut buf, 1, 6, 14, 3, mem, mem_color);
        draw_gauge(&mut buf, 1, 11, 14, 3, battery, bat_color);
    } else {
        let y_cpu_bar = scale_round_i32(6, size, 32);
        let y_mem_bar = scale_round_i32(16, size, 32);
        let y_bat_bar = scale_round_i32(26, size, 32);
        let bar_w = scale_round_i32(28, size, 32);
        let mut bar_h = scale_round_i32(3, size, 32);
        if bar_h < 3 {
            bar_h = 3;
        }
        draw_gauge(&mut buf, 2, y_cpu_bar, bar_w, bar_h, cpu, cpu_color);
        draw_gauge(&mut buf, 2, y_mem_bar, bar_w, bar_h, mem, mem_color);
        draw_gauge(&mut buf, 2, y_bat_bar, bar_w, bar_h, battery, bat_color);
    }

    buf
}

fn draw_triangle(buf: &mut [u8], size: i32, is_up: bool, color: (u8, u8, u8)) {
    // Rows are five at most and x stays on-panel: small and non-negative, so
    // the pixel offset crosses into `usize` once, here.
    let edge = usize::try_from(size).expect("panel edge is non-negative");
    if is_up {
        let rows = [(8, 8), (7, 9), (6, 10), (5, 11), (5, 11)];
        for (y, &(x0, x1)) in rows.iter().enumerate() {
            for x in x0..=x1 {
                let idx = (y * edge + usize::try_from(x).expect("triangle x is non-negative")) * 3;
                buf[idx] = color.0;
                buf[idx + 1] = color.1;
                buf[idx + 2] = color.2;
            }
        }
    } else {
        let rows = [(5, 11), (5, 11), (6, 10), (7, 9), (8, 8)];
        for (y, &(x0, x1)) in rows.iter().enumerate() {
            for x in x0..=x1 {
                let idx = (y * edge + usize::try_from(x).expect("triangle x is non-negative")) * 3;
                buf[idx] = color.0;
                buf[idx + 1] = color.1;
                buf[idx + 2] = color.2;
            }
        }
    }
}

fn draw_triangle_32(buf: &mut [u8], size: i32, is_up: bool, color: (u8, u8, u8)) {
    let y_range = if is_up {
        vec![
            (4, 25, 25),
            (5, 24, 26),
            (6, 23, 27),
            (7, 22, 28),
            (8, 21, 29),
            (9, 21, 29),
            (10, 21, 29),
        ]
    } else {
        vec![
            (10, 25, 25),
            (9, 24, 26),
            (8, 23, 27),
            (7, 22, 28),
            (6, 21, 29),
            (5, 21, 29),
            (4, 21, 29),
        ]
    };
    for (y, x0, x1) in y_range {
        for x in x0..=x1 {
            let idx = usize::try_from((y * size + x) * 3).expect("clipped triangle offset");
            buf[idx] = color.0;
            buf[idx + 1] = color.1;
            buf[idx + 2] = color.2;
        }
    }
}

/// Render `text` to a `size`x`size` RGB frame, centred, clipped to the matrix.
///
/// R70 P3.3. The GUI did this with a SECOND reader of the same font blob
/// (`divoom_lib/fonts/bitmap_font.py` over `divoom_fond16_default_half.bin`),
/// and then NEAREST-scaled the finished bitmap down to fit.
///
/// **Scaling a bitmap font destroys it, and the numbers are not close.** At
/// 16px with the half-size glyphs, "HELLO" already scales to 0.84x and loses
/// strokes; "HELLO WORLD" scales to 0.34x and renders as two rows of noise —
/// not hard to read, unreadable. Drawing at native size and CLIPPING shows
/// fewer characters and shows them intact, which is the version a person can
/// actually act on. (Scrolling is the real answer for long strings and is a
/// separate feature; the GUI's own docstring has said so since R32.)
///
/// Vertical centring is new and comes free: the glyphs occupy the top rows of
/// a 16-row cell, so the old path drew text hanging off the top edge.
pub(crate) fn render_text(text: &str, color: (u8, u8, u8), size: u32, full_font: bool) -> Vec<u8> {
    const GAP: i32 = 1;

    let edge = i32::try_from(size).expect("panel edge is non-negative");
    let mut buf = vec![0u8; usize::try_from(size * size * 3).expect("panel buffer fits usize")];
    let font = BitmapFont::new(if full_font {
        FONT_BYTES_FULL
    } else {
        FONT_BYTES
    });

    let width = font.measure_width(text, GAP);
    let x0 = if width < edge { (edge - width) / 2 } else { 0 };
    // Centre on the INK, not on the 16-row cell: the half-size glyphs sit in
    // the top of their cell, so cell-centring would still look top-heavy.
    let y0 = match font.ink_rows(text) {
        Some((top, bottom)) => {
            // Ink rows stay inside the 16-row cell: small by construction.
            let ink_h = i32::try_from(bottom - top + 1).expect("ink band fits i32");
            let top = i32::try_from(top).expect("ink top fits i32");
            ((edge - ink_h) / 2 - top).max(0)
        }
        None => 0,
    };
    let style = TextStyle {
        color,
        gap: GAP,
        max_width: Some(edge - x0),
    };
    font.draw_text(&mut buf, edge, x0, y0, text, &style);
    buf
}

pub(crate) fn render_stock(symbol: &str, price: f64, change: f64, size: u32) -> Vec<u8> {
    let edge = i32::try_from(size).expect("panel edge is non-negative");
    let mut buf = vec![0u8; usize::try_from(size * size * 3).expect("panel buffer fits usize")];
    for i in 0..usize::try_from(size * size).expect("panel pixels fit usize") {
        buf[i * 3] = 5;
        buf[i * 3 + 1] = 6;
        buf[i * 3 + 2] = 12;
    }

    let is_up = change >= 0.0;
    let text_color = if is_up { (0, 255, 180) } else { (255, 60, 60) };
    let font = BitmapFont::new(FONT_BYTES);

    if size == 16 {
        draw_triangle(&mut buf, edge, is_up, text_color);
        let label = TextStyle {
            color: (255, 255, 255),
            gap: 1,
            max_width: Some(edge),
        };
        font.draw_text(&mut buf, edge, 0, 6, &symbol.to_uppercase(), &label);
    } else {
        let label = TextStyle {
            color: (255, 255, 255),
            gap: 1,
            max_width: Some(edge - 2),
        };
        font.draw_text(&mut buf, edge, 2, 2, &symbol.to_uppercase(), &label);
        draw_triangle_32(&mut buf, edge, is_up, text_color);
        let price_style = TextStyle {
            color: text_color,
            ..label
        };
        font.draw_text(&mut buf, edge, 2, 16, &format!("${price:.2}"), &price_style);
    }

    buf
}

// --- macOS Battery stats ---

pub(crate) fn get_battery_percent() -> Option<u8> {
    let output = std::process::Command::new("pmset")
        .args(["-g", "batt"])
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&output.stdout);
    for line in text.lines() {
        if line.contains("InternalBattery") || line.contains("Drawing from") {
            if let Some(idx) = line.find('%') {
                let text_before = &line[..idx];
                if let Some(start) = text_before.rfind(|c: char| !c.is_numeric()) {
                    if let Ok(pct) = text_before[start + 1..].parse::<u8>() {
                        return Some(pct);
                    }
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The layout arithmetic must not fork.
    ///
    /// `measure_width` exists so `render_text` can centre, and it advances by
    /// the same rule `draw_text` does. Two measurements of one layout is the
    /// drift this whole round is removing, one level down — so they are pinned
    /// against each other rather than trusted to stay in step.
    #[test]
    fn measure_matches_draw_text() {
        let font = BitmapFont::new(FONT_BYTES);
        let mut buf = vec![0u8; 256 * 256 * 3];
        for text in ["A", "HI", "HELLO", "A B", "  ", "12:34", "!@#"] {
            let style = TextStyle {
                color: (255, 255, 255),
                gap: 1,
                max_width: None,
            };
            let drawn = font.draw_text(&mut buf, 256, 0, 0, text, &style);
            assert_eq!(
                font.measure_width(text, 1),
                drawn,
                "measure_width disagrees with draw_text for {text:?}"
            );
        }
    }

    #[test]
    fn ink_rows_finds_the_glyph_band() {
        let font = BitmapFont::new(FONT_BYTES);
        let (top, bottom) = font.ink_rows("HI").expect("HI has ink");
        assert!(top <= bottom);
        assert!(bottom < CELL, "ink cannot fall outside the cell");
        assert!(font.ink_rows("   ").is_none(), "spaces have no ink");
    }

    #[test]
    fn text_is_vertically_centred_rather_than_hanging_off_the_top() {
        // The half-size glyphs sit in the TOP of a 16-row cell, so drawing at
        // y=0 (what the GUI did) put text against the top edge.
        let rgb = render_text("HI", (255, 255, 255), 16, false);
        let lit_rows: Vec<usize> = (0..16)
            .filter(|&y| (0..16).any(|x| rgb[(y * 16 + x) * 3] > 0))
            .collect();
        assert!(!lit_rows.is_empty(), "nothing drawn");
        assert!(lit_rows[0] > 0, "text still starts at row 0");
        assert!(
            *lit_rows.last().unwrap() < 15,
            "text runs to the bottom edge"
        );
    }
}
