//! Byte-for-byte parity of the Rust FFI against the Python image encoders.
//! Vectors come from native-port/gen_image_vectors.py (the Python reference, which
//! routes through the same libdivoom_compact). A match confirms the FFI marshalling
//! is correct. Skips if the dylib isn't built.

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
    b.iter().map(|x| format!("{x:02x}")).collect()
}

#[test]
fn ffi_image_encoders_match_python() {
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
        let (w, h, t) = (
            c["w"].as_i64().unwrap() as i32,
            c["h"].as_i64().unwrap() as i32,
            c["time"].as_u64().unwrap() as u16,
        );
        let rgb = hex_to_bytes(c["rgb"].as_str().unwrap());
        let got = enc
            .encode_animation_frame(&rgb, w, h, t)
            .expect("frame encodes");
        assert_eq!(
            to_hex(&got),
            c["out"].as_str().unwrap(),
            "animation_frame {w}x{h}"
        );
    }
    for c in v["static"].as_array().unwrap() {
        let (w, h) = (
            c["w"].as_i64().unwrap() as i32,
            c["h"].as_i64().unwrap() as i32,
        );
        let rgb = hex_to_bytes(c["rgb"].as_str().unwrap());
        let got = enc.encode_static_image(&rgb, w, h).expect("static encodes");
        assert_eq!(
            to_hex(&got),
            c["out"].as_str().unwrap(),
            "static_image {w}x{h}"
        );
    }
    for c in v["frame32"].as_array().unwrap() {
        let (w, h, t) = (
            c["w"].as_i64().unwrap() as i32,
            c["h"].as_i64().unwrap() as i32,
            c["time"].as_u64().unwrap() as u16,
        );
        let rgb = hex_to_bytes(c["rgb"].as_str().unwrap());
        let got = enc
            .encode_animation_frame_32(&rgb, w, h, t)
            .expect("frame32 encodes");
        assert_eq!(
            to_hex(&got),
            c["out"].as_str().unwrap(),
            "animation_frame_32 {w}x{h}"
        );
    }
}
