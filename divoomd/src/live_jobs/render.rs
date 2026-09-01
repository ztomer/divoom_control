//! Pixel renderers for live-widget jobs: sysmon/stock frames, plus the macOS
//! battery probe. Pure compute (no I/O beyond `pmset`). The bitmap font lives
//! in `font.rs`.

pub use super::font::*;

// --- Renderers ---

pub(crate) fn render_sysmon(cpu: u8, mem: u8, battery: u8, size: u32) -> Vec<u8> {
    let mut buf = vec![0u8; (size * size * 3) as usize];
    for i in 0..(size * size) as usize {
        buf[i * 3] = 5;
        buf[i * 3 + 1] = 6;
        buf[i * 3 + 2] = 12;
    }

    let cpu_color = (255, 200, 0);
    let mem_color = (90, 170, 255);
    let bat_color = (255, 60, 60);

    let draw_gauge =
        |buf: &mut [u8], x: i32, y: i32, w_max: i32, h: i32, val: u8, color: (u8, u8, u8)| {
            let frac = val as f32 / 100.0;
            let w_fill = ((w_max as f32 * frac).round() as i32).clamp(1, w_max);
            for yy in y..y + h {
                if yy >= 0 && yy < size as i32 {
                    for xx in x..x + w_fill {
                        if xx >= 0 && xx < size as i32 {
                            let idx = ((yy * size as i32 + xx) * 3) as usize;
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
        let scale = size as f32 / 32.0;
        let y_cpu_bar = (6.0 * scale).round() as i32;
        let y_mem_bar = (16.0 * scale).round() as i32;
        let y_bat_bar = (26.0 * scale).round() as i32;
        let bar_w = (28.0 * scale).round() as i32;
        let mut bar_h = (3.0 * scale).round() as i32;
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
    if is_up {
        let rows = [(8, 8), (7, 9), (6, 10), (5, 11), (5, 11)];
        for (y, &(x0, x1)) in rows.iter().enumerate() {
            for x in x0..=x1 {
                let idx = ((y as i32 * size + x) * 3) as usize;
                buf[idx] = color.0;
                buf[idx + 1] = color.1;
                buf[idx + 2] = color.2;
            }
        }
    } else {
        let rows = [(5, 11), (5, 11), (6, 10), (7, 9), (8, 8)];
        for (y, &(x0, x1)) in rows.iter().enumerate() {
            for x in x0..=x1 {
                let idx = ((y as i32 * size + x) * 3) as usize;
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
            let idx = ((y * size + x) * 3) as usize;
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
    let mut buf = vec![0u8; (size * size * 3) as usize];
    let font = BitmapFont::new(if full_font {
        FONT_BYTES_FULL
    } else {
        FONT_BYTES
    });
    const GAP: i32 = 1;

    let width = font.measure_width(text, GAP);
    let x0 = if width < size as i32 {
        (size as i32 - width) / 2
    } else {
        0
    };
    // Centre on the INK, not on the 16-row cell: the half-size glyphs sit in
    // the top of their cell, so cell-centring would still look top-heavy.
    let y0 = match font.ink_rows(text) {
        Some((top, bottom)) => {
            let ink_h = (bottom - top + 1) as i32;
            ((size as i32 - ink_h) / 2 - top as i32).max(0)
        }
        None => 0,
    };
    font.draw_text(
        &mut buf,
        size as i32,
        x0,
        y0,
        text,
        color,
        GAP,
        Some(size as i32 - x0),
    );
    buf
}

pub(crate) fn render_stock(symbol: &str, price: f64, change: f64, size: u32) -> Vec<u8> {
    let mut buf = vec![0u8; (size * size * 3) as usize];
    for i in 0..(size * size) as usize {
        buf[i * 3] = 5;
        buf[i * 3 + 1] = 6;
        buf[i * 3 + 2] = 12;
    }

    let is_up = change >= 0.0;
    let text_color = if is_up { (0, 255, 180) } else { (255, 60, 60) };
    let font = BitmapFont::new(FONT_BYTES);

    if size == 16 {
        draw_triangle(&mut buf, size as i32, is_up, text_color);
        font.draw_text(
            &mut buf,
            size as i32,
            0,
            6,
            &symbol.to_uppercase(),
            (255, 255, 255),
            1,
            Some(size as i32),
        );
    } else {
        font.draw_text(
            &mut buf,
            size as i32,
            2,
            2,
            &symbol.to_uppercase(),
            (255, 255, 255),
            1,
            Some(size as i32 - 2),
        );
        draw_triangle_32(&mut buf, size as i32, is_up, text_color);
        font.draw_text(
            &mut buf,
            size as i32,
            2,
            16,
            &format!("${:.2}", price),
            text_color,
            1,
            Some(size as i32 - 2),
        );
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
            let drawn = font.draw_text(&mut buf, 256, 0, 0, text, (255, 255, 255), 1, None);
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
