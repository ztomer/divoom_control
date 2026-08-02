//! Pixel renderers for live-widget jobs: bitmap font + sysmon/stock frames,
//! plus the macOS battery probe. Pure compute (no I/O beyond `pmset`).

// --- Bitmap Font ---

const FIRST_CP: u32 = 0x20;
const LAST_CP: u32 = 0x7E;
const GLYPH_BYTES: usize = 32;
const CELL: usize = 16;
const FALLBACK_CP: u32 = 0x3F; // '?'

const FONT_BYTES: &[u8] =
    include_bytes!("../../../divoom_lib/fonts/divoom_fond16_default_half.bin");

struct BitmapFont {
    blob: &'static [u8],
    space_width: i32,
}

impl BitmapFont {
    fn new(blob: &'static [u8]) -> Self {
        Self {
            blob,
            space_width: 3,
        }
    }

    fn find_glyph_offset(&self, cp: u32) -> Option<usize> {
        if (FIRST_CP..=LAST_CP).contains(&cp) {
            Some(((cp - FIRST_CP) as usize) * GLYPH_BYTES)
        } else {
            None
        }
    }

    fn rows(&self, ch: char) -> [u16; 16] {
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

    fn col_bbox(&self, rows: &[u16; 16]) -> Option<(usize, usize)> {
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

    fn _char_width(&self, ch: char) -> i32 {
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

    #[expect(clippy::too_many_arguments)]
    fn draw_text(
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

// --- Renderers ---

pub(super) fn render_sysmon(cpu: u8, mem: u8, battery: u8, size: u32) -> Vec<u8> {
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

pub(super) fn render_stock(symbol: &str, price: f64, change: f64, size: u32) -> Vec<u8> {
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

pub(super) fn get_battery_percent() -> Option<u8> {
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
