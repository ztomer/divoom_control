//! The tray glyph, as pixels: a "D" whose SHAPE says the state (P7.1).
//!
//! Pure and std-only on purpose. `tray.rs` wraps these bytes in a
//! `tray_icon::Icon`, and `tools/render_tray_icon.py` compiles THIS file (with
//! `state.rs`, via `#[path]`) into a probe to draw its offscreen sheets, so the
//! sheet is the product's own renderer rather than a reproduction of it.
//! Nothing here may name a crate outside std, or the probe stops building.
//!
//! SIZE. tray-icon takes the bitmap's pixel height as its height in points,
//! shrinking anything taller than its 22pt cap to fit (0.26; 0.24 forced every
//! icon to 18pt instead). So the canvas is `W` x `H` = 36 x 44 px: the 22pt cap
//! makes that exactly 2x, crisp on Retina, and the status item keeps the 18pt
//! width and the optical size it had through v0.40. The geometry is authored
//! in a 22-unit square and scaled by `W / UNITS`.

/// Canvas width in pixels (18pt at 2x).
pub const W: u8 = 36;
/// Canvas height in pixels (22pt at 2x -- exactly tray-icon's height cap).
pub const H: u8 = 44;

/// How one state looks. Shape carries the state; `ink` only reinforces it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Look {
    /// The D's interior colour when FILLED (a device link exists); `None` is
    /// HOLLOW. The colour only reinforces: the fill's presence is the signal,
    /// and a hollow look cannot carry a colour it would never draw.
    pub fill: Option<[u8; 3]>,
    /// A diagonal bar strikes the D (something is at fault).
    pub barred: bool,
}

/// The outline's outer half: dark, so the silhouette survives a LIGHT bar.
const KEYLINE: [u8; 3] = [0x1c, 0x1c, 0x1e];
/// The outline's inner half: light, so the silhouette survives a DARK bar.
const HALO: [u8; 3] = [0xf5, 0xf5, 0xf5];

/// RGBA for `look`, plus its dimensions.
///
/// Every state shares one two-tone outline -- dark outside, light inside --
/// because no single tone is visible on both bars: the `#F5F5F5`-only border
/// this replaced vanished on a light bar, leaving the glyph only its fill.
/// Inside the outline the D is its `fill` colour or left clear (hollow); a barred
/// look adds a "/" stroke made of the outline's own two tones (a light core
/// between dark keylines), so it reads over any fill, over a clear interior,
/// and on either bar.
#[must_use]
pub fn draw(look: Look) -> (Vec<u8>, u32, u32) {
    const UNITS: f32 = 22.0;
    const MARGIN: f32 = 3.0;
    const STROKE: f32 = 2.2;
    const BAR: f32 = 2.2; // half the bar's width, in design units
    const BAR_KEYLINE: f32 = 0.9;
    const SUBSAMPLES: u8 = 4;

    let width = usize::from(W);
    let cells = u16::from(SUBSAMPLES) * u16::from(SUBSAMPLES);
    let k = f32::from(W) / UNITS;
    let stroke = STROKE * k;
    let left = MARGIN * k;
    let radius = (UNITS / 2.0 - MARGIN) * k;
    let mid = left + radius;
    let right = mid + radius;
    let cy = f32::from(H) / 2.0;
    let top = cy - radius;
    let bottom = cy + radius;
    let bar_half = BAR * k;
    let bar_keyline = BAR_KEYLINE * k;

    // Depth inside the D's silhouette (a rectangle unioned with a half-disc on
    // its right edge); negative outside.
    let depth = |fx: f32, fy: f32| -> f32 {
        if fx <= mid {
            (fx - left).min(fy - top).min(bottom - fy)
        } else {
            radius - (fx - mid).hypot(fy - cy)
        }
    };
    // Distance from the "/" diagonal of the D's bounding square, and whether
    // the point lies along it (the bar is clipped to that square).
    let bar = |fx: f32, fy: f32| -> Option<f32> {
        let along = (fx - left + bottom - fy) / std::f32::consts::SQRT_2;
        let len = (right - left) * std::f32::consts::SQRT_2;
        let off = ((fx - left) - (bottom - fy)).abs() / std::f32::consts::SQRT_2;
        (along >= 0.0 && along <= len && off <= bar_half).then_some(off)
    };

    let sample = |fx: f32, fy: f32| -> Option<[u8; 3]> {
        if look.barred {
            if let Some(off) = bar(fx, fy) {
                return Some(if off >= bar_half - bar_keyline {
                    KEYLINE
                } else {
                    HALO
                });
            }
        }
        let d = depth(fx, fy);
        if d < 0.0 {
            None
        } else if d < stroke / 2.0 {
            Some(KEYLINE)
        } else if d < stroke {
            Some(HALO)
        } else {
            look.fill
        }
    };

    let mut rgba = vec![0u8; width * usize::from(H) * 4];
    for y in 0..H {
        for x in 0..W {
            // Supersampled: alpha is the covered share, colour the mean of the
            // covered samples (integer sums, so no float-to-byte narrowing).
            let mut coverage = 0u16;
            let mut sum = [0u16; 3];
            for sy in 0..SUBSAMPLES {
                for sx in 0..SUBSAMPLES {
                    let fx = f32::from(x) + (f32::from(sx) + 0.5) / f32::from(SUBSAMPLES);
                    let fy = f32::from(y) + (f32::from(sy) + 0.5) / f32::from(SUBSAMPLES);
                    if let Some(c) = sample(fx, fy) {
                        coverage += 1;
                        for (acc, v) in sum.iter_mut().zip(c) {
                            *acc += u16::from(v);
                        }
                    }
                }
            }
            if coverage == 0 {
                continue;
            }
            let i = (usize::from(y) * width + usize::from(x)) * 4;
            for (c, acc) in sum.iter().enumerate() {
                rgba[i + c] = u8::try_from((acc + coverage / 2) / coverage)
                    .expect("a mean of bytes is a byte");
            }
            rgba[i + 3] = u8::try_from((coverage * 255 + cells / 2) / cells)
                .expect("subsample coverage scales to one byte");
        }
    }
    (rgba, u32::from(W), u32::from(H))
}

#[cfg(test)]
mod tests {
    //! Never one channel (ui-house-doctrine rule 9): every pair of tray states
    //! must differ in GREYSCALE, at every size the menu bar shows the glyph,
    //! on a light AND a dark bar -- and must still differ when every state is
    //! drawn in ONE colour, which is the claim that shape, not colour, carries.

    use super::{draw, Look, H, W};
    use crate::state::IconState;

    /// Flat approximations of the two menu bars (as `tools/render_tray_icon.py`).
    const BARS: [(&str, u8); 2] = [("light", 0xEC), ("dark", 0x2A)];
    /// A greyscale step a reader can see at a glance: a quarter of the range.
    const VISIBLE: f32 = 64.0;
    /// One colour for every state, to take colour away entirely.
    const ONE_INK: [u8; 3] = [0x8E, 0x8E, 0x93];

    fn luma(r: f32, g: f32, b: f32) -> f32 {
        0.0722f32.mul_add(b, 0.2126f32.mul_add(r, 0.7152 * g))
    }

    /// Composite `rgba` over a grey bar and reduce it to luma, at `scale`
    /// device pixels per point (2 = Retina, as drawn; 1 = a 1x display, where
    /// `AppKit` box-filters each 2x2 block).
    fn grey(rgba: &[u8], bar: u8, scale: usize) -> Vec<f32> {
        let (w, h) = (usize::from(W), usize::from(H));
        let bg = f32::from(bar);
        let full: Vec<f32> = rgba
            .as_chunks::<4>()
            .0
            .iter()
            .map(|p| {
                let a = f32::from(p[3]) / 255.0;
                let c = |v: u8| f32::from(v).mul_add(a, bg * (1.0 - a));
                luma(c(p[0]), c(p[1]), c(p[2]))
            })
            .collect();
        if scale == 2 {
            return full;
        }
        let mut out = Vec::with_capacity(w * h / 4);
        for y in (0..h).step_by(2) {
            for x in (0..w).step_by(2) {
                let s = full[y * w + x]
                    + full[y * w + x + 1]
                    + full[(y + 1) * w + x]
                    + full[(y + 1) * w + x + 1];
                out.push(s / 4.0);
            }
        }
        out
    }

    fn differing(a: &[f32], b: &[f32]) -> usize {
        a.iter()
            .zip(b)
            .filter(|(x, y)| (*x - *y).abs() >= VISIBLE)
            .count()
    }

    /// A pair must differ in at least this share of the glyph's square
    /// (W x W at 2x): a bar or a fill, never a stray edge pixel.
    fn floor(scale: usize) -> usize {
        let side = usize::from(W) * scale / 2;
        side * side / 20
    }

    fn assert_pairwise_distinct(render: impl Fn(IconState) -> Vec<u8>, what: &str) {
        for (bar_name, bar) in BARS {
            for scale in [2, 1] {
                for (i, a) in IconState::ALL.iter().enumerate() {
                    for b in &IconState::ALL[i + 1..] {
                        let n = differing(
                            &grey(&render(*a), bar, scale),
                            &grey(&render(*b), bar, scale),
                        );
                        assert!(
                            n >= floor(scale),
                            "{what}: {a:?} and {b:?} differ in only {n} px (need {}) in \
                             greyscale on the {bar_name} bar at {scale}x",
                            floor(scale)
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn every_pair_of_states_differs_in_greyscale_on_light_and_dark_bars() {
        assert_pairwise_distinct(|s| draw(s.look()).0, "real colours");
    }

    #[test]
    fn shape_alone_carries_every_state() {
        assert_pairwise_distinct(
            |s| {
                let look = s.look();
                draw(Look {
                    fill: look.fill.map(|_| ONE_INK),
                    ..look
                })
                .0
            },
            "one colour for all states",
        );
    }

    /// The hollow state is the ABSENCE of the fill, so price the ink left:
    /// on both bars every state must keep a visible outline, not just a fill.
    #[test]
    fn every_state_keeps_visible_ink_on_both_bars() {
        let clear = vec![0u8; usize::from(W) * usize::from(H) * 4];
        for (bar_name, bar) in BARS {
            for scale in [2, 1] {
                let empty = grey(&clear, bar, scale);
                for s in IconState::ALL {
                    let n = differing(&grey(&draw(s.look()).0, bar, scale), &empty);
                    assert!(
                        n >= 2 * floor(scale),
                        "{s:?} shows only {n} visible px on the {bar_name} bar at {scale}x"
                    );
                }
            }
        }
    }

    /// Calibration: the gate must go red when two states share a look.
    #[test]
    fn the_distinctness_check_can_fail() {
        let same = |_: IconState| draw(IconState::Connected.look()).0;
        let caught = std::panic::catch_unwind(|| assert_pairwise_distinct(same, "calibration"));
        assert!(
            caught.is_err(),
            "identical glyphs passed the distinctness gate"
        );
    }
}
