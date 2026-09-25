//! Panel image bodies: palette dedup, then LSB-first bit packing.
//!
//! Two commands share this body and differ only in their header, so they share
//! one implementation here exactly as they share one in the C (`image_encode.c`:
//! "Palette dedup (same as animation frame)"):
//!
//! * `encode_animation_frame` — 0x49, header `AA LLLL(2) TTTT(2) RR NN`, where
//!   `TTTT` is the frame duration in ms and `RR` is the palette-reset flag.
//! * `encode_static_image` — 0x44, header `AA LLLL(2) 00 00 00 NN`, where the
//!   three zero bytes stand in for `TTTT`+`RR` (no duration, no reset).
//!
//! Ported from `divoom_lib/native_src/image_encode.c` (phase L4), op for op, and
//! asserted byte-for-byte against that C library's own recorded output — 103
//! cases in `divoomd/tests/image_vectors.json` spanning 13 sizes (non-square,
//! single-pixel, 64x64) and 6 colour counts, captured from the dylib and
//! cross-checked against the Python reference as the vectors were recorded.
//!
//! Two things about the original are load-bearing and easy to get wrong:
//!
//! * **Palette order is first appearance, not hash order.**
//!
//!   The C keeps a
//!   512-slot open-addressing table (Thomas Wang's `hash32`) purely to find an
//!   existing colour fast; the index handed back is `palette_n++`, so the
//!   emitted palette is the order pixels were first seen. The hash function
//!   therefore cannot affect a single output byte, and this port does not
//!   reproduce `hash32` — it uses a `HashMap` for the same lookup job. A reader
//!   comparing this to the C and looking for the hash will not find it, and this
//!   comment is why that is correct rather than a shortcut.
//! * **The per-pixel indices live in their own buffer.**
//!
//!   The C comment records
//!   the bug: aliasing them onto the output buffer overwrote indices that were
//!   still to be read (`7 + 3*n < i`), which silently diverged from the Python
//!   reference. Here they are a `Vec<u8>` and the output is assembled after,
//!   so the hazard cannot be expressed.
//!
//! The `out_buf_size` check in the C is an FFI-buffer concern, not a semantic
//! one — the caller sizes the buffer to the C's own worst case — so it lives in
//! the FFI wrapper, not here.

/// Bytes of frame header: `AA LLLL(2) TTTT(2) RR NN`.
pub const FRAME_HEADER_SIZE: usize = 7;

/// Colours the protocol's `NN` byte can address.
pub const PALETTE_MAX: usize = 256;

/// The only panel size the 32x32 encoder accepts, in pixels per side.
pub const SCREEN_SIZE_32: usize = 32;

/// Largest frame the C accepts, in pixels (`w * h > 65535` → refuse).
///
/// The bound is the C's, and it is a refusal rather than a clamp: past it the
/// frame index buffer and the length arithmetic stop being trustworthy, and a
/// silently truncated frame is a device showing the wrong thing.
const MAX_PIXELS: usize = 65535;

/// Why a frame was refused. The C returns `-1` for all of these; naming them
/// costs nothing and turns "the encoder said no" into a sentence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    /// `w <= 0 || h <= 0`, or a null buffer at the FFI edge.
    EmptyPanel,
    /// `w * h > 65535`.
    TooManyPixels,
    /// More than 256 unique colours, which the palette cannot address.
    PaletteFull,
    /// The 32x32 encoder's own gate: it accepts 32x32 and nothing else.
    NotA32x32Panel,
}

impl core::fmt::Display for Refusal {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        let why = match self {
            Self::EmptyPanel => "the panel has a zero dimension",
            Self::TooManyPixels => "more than 65535 pixels",
            Self::PaletteFull => "more than 256 unique colours",
            Self::NotA32x32Panel => "the 32x32 encoder only accepts a 32x32 panel",
        };
        f.write_str(why)
    }
}

/// The palette and the packed pixels, before any header.
struct Packed {
    /// Distinct colours in first-appearance order.
    palette: Vec<[u8; 3]>,
    /// Packed pixel bytes, LSB-first.
    pixels: Vec<u8>,
}

/// The body both commands share: validate, dedup the palette, pack the pixels.
///
/// # Errors
///
/// [`Refusal::EmptyPanel`] for a zero dimension or a short `rgb`, which is what
/// the C answered with `-1`; [`Refusal::TooManyPixels`] past 65535 pixels; and
/// [`Refusal::PaletteFull`] on the 257th unique colour. Every one of those is a
/// refusal rather than a clamp, because a clamped frame is a device showing
/// something nobody asked for.
fn pack(rgb: &[u8], w: i32, h: i32) -> Result<Packed, Refusal> {
    if w <= 0 || h <= 0 {
        return Err(Refusal::EmptyPanel);
    }
    // The counts are bounded by the refusals above, so these conversions cannot
    // fail; `try_from` rather than `as` because that is the habit, not because
    // there is a case where it matters.
    let (w, h) = (
        usize::try_from(w).map_err(|_| Refusal::EmptyPanel)?,
        usize::try_from(h).map_err(|_| Refusal::EmptyPanel)?,
    );
    let num_pixels = w.checked_mul(h).ok_or(Refusal::TooManyPixels)?;
    if num_pixels > MAX_PIXELS {
        return Err(Refusal::TooManyPixels);
    }
    if rgb.len() < num_pixels * 3 {
        return Err(Refusal::EmptyPanel);
    }

    // ---- palette dedup, in first-appearance order ----
    let mut palette: Vec<[u8; 3]> = Vec::new();
    let mut seen: std::collections::HashMap<[u8; 3], u8> = std::collections::HashMap::new();
    let mut indices: Vec<u8> = Vec::with_capacity(num_pixels);
    for i in 0..num_pixels {
        let key = [rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]];
        let index = if let Some(&found) = seen.get(&key) {
            found
        } else {
            if palette.len() >= PALETTE_MAX {
                return Err(Refusal::PaletteFull);
            }
            let fresh = u8::try_from(palette.len()).map_err(|_| Refusal::PaletteFull)?;
            palette.push(key);
            seen.insert(key, fresh);
            fresh
        };
        indices.push(index);
    }

    let bits = bits_per_index(palette.len());
    let mut pixels = Vec::with_capacity(num_pixels * bits / 8 + 1);

    // ---- pixels, LSB-first into LSB-first bytes ----
    let mask = (1u32 << bits) - 1;
    let mut acc: u32 = 0;
    let mut acc_bits: u32 = 0;
    for &index in &indices {
        acc |= u32::from(index & u8::try_from(mask).unwrap_or(u8::MAX)) << acc_bits;
        acc_bits += u32::try_from(bits).unwrap_or(0);
        while acc_bits >= 8 {
            pixels.push(u8::try_from(acc & 0xFF).unwrap_or(0));
            acc >>= 8;
            acc_bits -= 8;
        }
    }
    if acc_bits > 0 {
        pixels.push(u8::try_from(acc & 0xFF).unwrap_or(0));
    }

    Ok(Packed { palette, pixels })
}

/// Bits per palette index: `ceil(log2(n))`, and 1 for a single colour.
///
/// The `n == 1` case is not an optimisation, it is required: `ceil(log2(1))` is
/// 0, and a zero-width index would make the packer emit no pixel bytes at all.
/// The C special-cases it the same way.
const fn bits_per_index(colours: usize) -> usize {
    if colours > 1 {
        usize::BITS as usize - (colours - 1).leading_zeros() as usize
    } else {
        1
    }
}

/// Encode one 32x32 animation frame body — the same bytes as
/// [`encode_animation_frame`] for a 32x32 panel, and refused for anything else.
///
/// The C's `divoom_encode_animation_frame_32` is the 0x49 algorithm with one
/// extra guard: `if (w != 32 || h != 32) return -1`. Its comment says the header
/// is the `standard AA format matching APK's pixelEncode() for ALL screen
/// sizes`, which is why this delegates instead of re-deriving: a third copy of
/// the packer is a third thing to keep in step, and the recorded 32x32 vectors
/// are what says the two really are the same function.
///
/// # Errors
///
/// [`Refusal::NotA32x32Panel`] for any other size — the C's own gate, which
/// exists because a 32x32 frame body is only meaningful for a 32x32 panel — and
/// otherwise whatever [`pack`] refuses.
pub fn encode_animation_frame_32(
    rgb: &[u8],
    w: i32,
    h: i32,
    time_ms: u16,
) -> Result<Vec<u8>, Refusal> {
    if w != i32::try_from(SCREEN_SIZE_32).unwrap_or(i32::MAX)
        || h != i32::try_from(SCREEN_SIZE_32).unwrap_or(i32::MAX)
    {
        return Err(Refusal::NotA32x32Panel);
    }
    encode_animation_frame(rgb, w, h, time_ms)
}

/// Assemble `[AA LLLL(2) header-tail][palette][pixels]`.
///
/// `LLLL` is computed here rather than passed in, because it is a function of
/// what follows: header + palette + pixels. A caller that supplied it would be
/// able to disagree with the bytes it is describing, which is the bug the C's
/// own comment records for the 0x44 header (it was 6 bytes, so `NN` got
/// clobbered by the palette copy and `LLLL` undercounted by one).
fn assemble(tail: [u8; 4], packed: &Packed) -> Vec<u8> {
    let color_data_bytes = packed.palette.len() * 3;
    let llll = FRAME_HEADER_SIZE + color_data_bytes + packed.pixels.len();

    let mut out = Vec::with_capacity(llll);
    out.push(0xAA);
    out.push(u8::try_from(llll & 0xFF).unwrap_or(0));
    out.push(u8::try_from((llll >> 8) & 0xFF).unwrap_or(0));
    out.extend_from_slice(&tail);
    for colour in &packed.palette {
        out.extend_from_slice(colour);
    }
    out.extend_from_slice(&packed.pixels);
    debug_assert_eq!(out.len(), llll, "header length must match what was written");
    out
}

/// Encode one 0x49 animation frame body from packed RGB.
///
/// # Errors
///
/// Whatever [`pack`] refuses, for the same reasons.
pub fn encode_animation_frame(
    rgb: &[u8],
    w: i32,
    h: i32,
    time_ms: u16,
) -> Result<Vec<u8>, Refusal> {
    let packed = pack(rgb, w, h)?;
    // AA LLLL(2) TTTT(2) RR NN — TTTT is the frame duration, RR resets the
    // palette. NN is filled in by `assemble`'s caller contract below.
    let tail = [
        u8::try_from(time_ms & 0xFF).unwrap_or(0),
        u8::try_from((time_ms >> 8) & 0xFF).unwrap_or(0),
        0x00, // RR = reset palette
        u8::try_from(packed.palette.len()).unwrap_or(0),
    ];
    Ok(assemble(tail, &packed))
}

/// Encode one 0x44 static image body from packed RGB.
///
/// # Errors
///
/// Whatever [`pack`] refuses, for the same reasons.
pub fn encode_static_image(rgb: &[u8], w: i32, h: i32) -> Result<Vec<u8>, Refusal> {
    let packed = pack(rgb, w, h)?;
    // AA LLLL(2) 00 00 00 NN — the three zeros stand in for TTTT(2)+RR(1): a
    // static image has no duration and no palette reset.
    let tail = [
        0x00,
        0x00,
        0x00,
        u8::try_from(packed.palette.len()).unwrap_or(0),
    ];
    Ok(assemble(tail, &packed))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rgb_of(hex: &str) -> Vec<u8> {
        (0..hex.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).expect("hex"))
            .collect()
    }

    /// Every recorded case, from the C library itself.
    fn vectors() -> serde_json::Value {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/image_vectors.json");
        let raw = std::fs::read_to_string(path).expect("read image_vectors.json");
        serde_json::from_str(&raw).expect("vectors parse")
    }

    #[test]
    fn every_recorded_frame_reproduces() {
        let cases = vectors()["frame"].as_array().expect("frame cases").clone();
        let mut checked = 0;
        let mut refusals = 0;
        for case in &cases {
            let w = i32::try_from(case["w"].as_i64().expect("w")).expect("w fits i32");
            let h = i32::try_from(case["h"].as_i64().expect("h")).expect("h fits i32");
            let t = u16::try_from(case["time"].as_u64().expect("time")).expect("time fits u16");
            let rgb = rgb_of(case["rgb"].as_str().expect("rgb"));
            let got = encode_animation_frame(&rgb, w, h, t);
            if case.get("refused").is_some() {
                assert!(
                    got.is_err(),
                    "{w}x{h} t={t}: the C refused this case and the port emitted \
                     {} bytes",
                    got.as_ref().map_or(0, Vec::len)
                );
                refusals += 1;
                continue;
            }
            let want = case["out"].as_str().expect("out hex");
            assert_eq!(
                crate::wire::hex(&got.expect("frame encodes")),
                want,
                "frame {w}x{h} t={t} diverged from the C"
            );
            checked += 1;
        }
        assert!(
            checked >= 100,
            "only {checked} frame vectors: the sweep shrank"
        );
        assert_eq!(refusals, 1, "expected exactly the zero-dimension refusal");
    }

    #[test]
    fn every_recorded_static_image_reproduces() {
        let cases = vectors()["static"]
            .as_array()
            .expect("static cases")
            .clone();
        let mut checked = 0;
        let mut refusals = 0;
        for case in &cases {
            let w = i32::try_from(case["w"].as_i64().expect("w")).expect("w fits i32");
            let h = i32::try_from(case["h"].as_i64().expect("h")).expect("h fits i32");
            let rgb = rgb_of(case["rgb"].as_str().expect("rgb"));
            let got = encode_static_image(&rgb, w, h);
            if case.get("refused").is_some() {
                assert!(
                    got.is_err(),
                    "{w}x{h}: the C refused this case and the port emitted {} bytes",
                    got.as_ref().map_or(0, Vec::len)
                );
                refusals += 1;
                continue;
            }
            assert_eq!(
                crate::wire::hex(&got.expect("static encodes")),
                case["out"].as_str().expect("out hex"),
                "static {w}x{h} diverged from the C"
            );
            checked += 1;
        }
        assert!(
            checked >= 75,
            "only {checked} static vectors: the sweep shrank"
        );
        assert_eq!(refusals, 1, "expected exactly the zero-dimension refusal");
    }

    #[test]
    fn every_recorded_32x32_frame_reproduces() {
        let cases = vectors()["frame32"]
            .as_array()
            .expect("frame32 cases")
            .clone();
        assert!(cases.len() >= 8, "the 32x32 sweep shrank");
        for case in &cases {
            let w = i32::try_from(case["w"].as_i64().expect("w")).expect("w fits i32");
            let h = i32::try_from(case["h"].as_i64().expect("h")).expect("h fits i32");
            let t = u16::try_from(case["time"].as_u64().expect("time")).expect("time fits u16");
            let rgb = rgb_of(case["rgb"].as_str().expect("rgb"));
            assert_eq!(
                crate::wire::hex(&encode_animation_frame_32(&rgb, w, h, t).expect("encodes")),
                case["out"].as_str().expect("out hex"),
                "32x32 frame t={t} diverged from the C"
            );
        }
    }

    #[test]
    fn the_32x32_encoder_refuses_every_other_size() {
        // The C's gate, and the reason it exists: a 32x32 frame body is only
        // meaningful for a 32x32 panel, so a 16x16 image handed here is a caller
        // bug rather than something to resize on the way through.
        let rgb = vec![0x20u8; 3 * 32 * 32];
        assert!(encode_animation_frame_32(&rgb, 32, 32, 500).is_ok());
        for (w, h) in [(16, 16), (31, 32), (32, 31), (64, 64), (0, 32), (32, 0)] {
            assert_eq!(
                encode_animation_frame_32(&rgb, w, h, 500).unwrap_err(),
                Refusal::NotA32x32Panel,
                "{w}x{h} should be refused"
            );
        }
    }

    #[test]
    fn a_32x32_frame_is_the_same_bytes_as_the_general_encoder() {
        // The claim the delegation rests on, asserted directly: for a 32x32 panel
        // the two encoders produce identical output. If they ever stop agreeing,
        // the delegation is wrong and this is what says so.
        let rgb: Vec<u8> = (0..(32 * 32 * 3))
            .map(|i| u8::try_from(i % 251).unwrap_or(0))
            .collect();
        assert_eq!(
            encode_animation_frame_32(&rgb, 32, 32, 777).expect("encodes"),
            encode_animation_frame(&rgb, 32, 32, 777).expect("encodes"),
        );
    }

    #[test]
    fn the_two_commands_differ_only_in_their_header_tail() {
        // The claim the shared `pack` rests on: same body, different header. If
        // this ever fails, the two commands have genuinely diverged and one
        // shared implementation is no longer the right shape.
        let rgb: Vec<u8> = (0..(7 * 5 * 3))
            .map(|i| u8::try_from(i % 251).unwrap_or(0))
            .collect();
        let frame = encode_animation_frame(&rgb, 7, 5, 0x1234).expect("frame encodes");
        let still = encode_static_image(&rgb, 7, 5).expect("static encodes");
        assert_eq!(frame.len(), still.len(), "the body is the same size");
        assert_eq!(frame[0], still[0], "AA");
        assert_eq!(frame[1..3], still[1..3], "LLLL");
        // Bytes 3.. are the only difference: TTTT+RR against three zeros.
        assert_eq!(frame[3..7], [0x34, 0x12, 0x00, frame[6]]);
        assert_eq!(still[3..7], [0x00, 0x00, 0x00, still[6]]);
        assert_eq!(frame[7..], still[7..], "palette and pixels are identical");
    }

    #[test]
    fn a_single_colour_still_occupies_one_bit_each() {
        // nb_bits of 0 would make the packer emit nothing at all, which is why
        // the C special-cases n == 1. Pinned because it is the one place the
        // bit-width arithmetic has a branch.
        let flat = vec![0x40u8; 3 * 16];
        let frame = encode_animation_frame(&flat, 4, 4, 500).expect("encodes");
        assert_eq!(frame[6], 1, "NN is the colour count");
        // 7 header + 3 palette + 2 bytes of packed indices (16 px at 1 bit).
        assert_eq!(frame.len(), 7 + 3 + 2);
    }

    #[test]
    fn the_refusals_are_the_c_s_refusals() {
        assert_eq!(
            encode_animation_frame(&[], 0, 0, 0).unwrap_err(),
            Refusal::EmptyPanel
        );
        assert_eq!(
            encode_animation_frame(&[0; 3], 1, 0, 0).unwrap_err(),
            Refusal::EmptyPanel
        );
        // 257 unique colours: the 257th has nowhere to go.
        let mut rainbow = Vec::with_capacity(257 * 3);
        for i in 0..257u16 {
            rainbow.extend_from_slice(&[
                u8::try_from(i >> 8).unwrap_or(0),
                u8::try_from(i).unwrap_or(0),
                0,
            ]);
        }
        assert_eq!(
            encode_animation_frame(&rainbow, 257, 1, 0).unwrap_err(),
            Refusal::PaletteFull
        );
    }

    #[test]
    fn palette_order_is_first_appearance() {
        // Not sorted, not hashed: the order pixels were first seen, which is what
        // makes the output reproducible across implementations. A sorted palette
        // would also "work" on a device and would not match the C.
        //
        // The pixels are named rather than written as one flat literal because a
        // flat literal is exactly how the first draft of this test ended up with
        // two colours where it meant three — and the failure read as a port bug.
        const BLUE: [u8; 3] = [0x00, 0x00, 0xFF];
        const RED: [u8; 3] = [0xFF, 0x00, 0x00];
        const BLACK: [u8; 3] = [0x00, 0x00, 0x00];
        let mut rgb = Vec::new();
        for pixel in [BLUE, RED, BLACK, BLUE] {
            rgb.extend_from_slice(&pixel);
        }

        let frame = encode_animation_frame(&rgb, 2, 2, 500).expect("encodes");
        assert_eq!(frame[6], 3, "NN is the distinct colour count");

        let palette = &frame[FRAME_HEADER_SIZE..FRAME_HEADER_SIZE + 9];
        let mut expected = Vec::new();
        for colour in [BLUE, RED, BLACK] {
            expected.extend_from_slice(&colour);
        }
        assert_eq!(
            palette,
            expected.as_slice(),
            "palette is in first-seen order"
        );
    }
}
