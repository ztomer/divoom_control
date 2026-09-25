//! Byte-for-byte parity of the Rust FFI against the C library's OWN recorded bytes.
//!
//! Vectors come from `scripts/codegen/gen_image_vectors.py`, which captures them
//! from `libdivoom_compact` itself and cross-checks each one against the Python
//! reference in `examples/divoom_legacy` — 192 cases across 13 sizes (non-square,
//! single-pixel, larger-than-panel so the LANCZOS3 downsampler runs) and 6 colour
//! counts, plus the one case where the two implementations differ: a ZERO
//! dimension, where the C refuses and Python emits a degenerate frame. That
//! refusal is recorded as a refusal, and asserted as one.
//!
//! Two jobs, both real. It proves the FFI marshalling (pointers, out-buffer
//! sizing, return-length truncation) is correct, and it is the ORACLE for phase
//! L4's port of these encoders to Rust: the bytes here are what the port has to
//! reproduce. Skips if the dylib isn't built, which is why that skip is a
//! printed line rather than a silent pass.

use divoomd::native_encode::NativeEncoder;
use serde_json::Value;
use std::fs;

fn dylib_path() -> String {
    // crate is divoomd; the dylib lives at <repo>/divoom_lib/.
    let base = concat!(env!("CARGO_MANIFEST_DIR"), "/../../divoom_lib/");
    for name in ["libdivoom_compact.dylib", "libdivoom_compact.so"] {
        let p = format!("{base}{name}");
        if std::path::Path::new(&p).exists() {
            return p;
        }
    }
    String::new()
}

fn vectors() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/image_vectors.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn hex_to_bytes(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}
fn to_hex(b: &[u8]) -> String {
    divoomd::wire::hex(b)
}

/// A recorded case, and whether the C REFUSED it.
///
/// `refused` is a first-class outcome, not a missing field. The vectors record
/// one: at a zero dimension the C returns an error while the python reference
/// emits a degenerate frame. Asserting that case produces bytes would force the
/// test to treat a refusal as a zero-length success, which is the same confusion
/// the refusal exists to prevent.
fn case(c: &Value) -> (i32, i32, u16, Vec<u8>, Option<String>) {
    let w = i32::try_from(c["w"].as_i64().expect("width")).expect("w fits i32");
    let h = i32::try_from(c["h"].as_i64().expect("height")).expect("h fits i32");
    let t = c["time"].as_u64().unwrap_or(0);
    let t = u16::try_from(t).expect("time fits u16");
    let rgb = c["rgb"].as_str().map_or_else(Vec::new, hex_to_bytes);
    let out = if c.get("refused").is_some() {
        None
    } else {
        Some(c["out"].as_str().expect("out hex").to_string())
    };
    (w, h, t, rgb, out)
}

#[test]
fn ffi_image_encoders_match_the_recorded_c_bytes() {
    let path = dylib_path();
    if path.is_empty() {
        eprintln!("SKIP: libdivoom_compact not built — run scripts/build_libdivoom.sh");
        return;
    }
    // Skip (don't panic) if the dylib can't be loaded — e.g. the repo ships a
    // prebuilt macOS .dylib that the Linux no-ble CI job finds but can't dlopen
    // ("invalid ELF header"). Wrong-arch == effectively "not built here".
    let enc = match NativeEncoder::load(&path) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("SKIP: cannot load {path}: {e}");
            return;
        }
    };
    let v = vectors();

    for c in v["frame"].as_array().unwrap() {
        let (w, h, t, rgb, expected) = case(c);
        let got = enc.encode_animation_frame(&rgb, w, h, t);
        match expected {
            Some(want) => assert_eq!(
                to_hex(&got.expect("frame encodes")),
                want,
                "animation_frame {w}x{h} t={t}"
            ),
            None => assert!(
                got.is_none(),
                "animation_frame {w}x{h} t={t}: the C refused this case and the \
                 FFI wrapper turned the refusal into {:?}",
                got.map(|b| b.len())
            ),
        }
    }
    for c in v["static"].as_array().unwrap() {
        let (w, h, _t, rgb, expected) = case(c);
        let got = enc.encode_static_image(&rgb, w, h);
        match expected {
            Some(want) => assert_eq!(
                to_hex(&got.expect("static encodes")),
                want,
                "static_image {w}x{h}"
            ),
            None => assert!(
                got.is_none(),
                "static_image {w}x{h}: the C refused this case and the FFI \
                 wrapper turned the refusal into {:?}",
                got.map(|b| b.len())
            ),
        }
    }
    for c in v["frame32"].as_array().unwrap() {
        let (w, h, t, rgb, expected) = case(c);
        let got = enc.encode_animation_frame_32(&rgb, w, h, t);
        match expected {
            Some(want) => assert_eq!(
                to_hex(&got.expect("frame32 encodes")),
                want,
                "animation_frame_32 {w}x{h} t={t}"
            ),
            None => assert!(
                got.is_none(),
                "animation_frame_32 {w}x{h} t={t}: the C refused this case"
            ),
        }
    }
}
