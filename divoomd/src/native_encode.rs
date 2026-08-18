//! FFI to the existing C image encoders in `libdivoom_compact` — the plan's
//! "reuse the C encoders via FFI initially, port to native Rust later". Loaded
//! dynamically at runtime (like Python's `ctypes.CDLL`), so there's no link-time
//! dependency and a missing dylib degrades gracefully (the caller can fall back).
//!
//! These call the SAME C functions the Python daemon uses (the palette encoder
//! fixed this session), so byte-parity against the Python output is the contract
//! (`tests/native_encode_parity.rs`).

use std::ffi::OsStr;

use libloading::{Library, Symbol};

/// Find the libdivoom_compact dylib: `DIVOOMD_ENCODER_LIB` env override, else
/// relative to the running binary (project-root `divoom_lib/`).
pub fn find_encoder_lib() -> Option<std::path::PathBuf> {
    if let Ok(p) = std::env::var("DIVOOMD_ENCODER_LIB") {
        let pb = std::path::PathBuf::from(&p);
        if pb.exists() {
            return Some(pb);
        }
    }
    // Search UP for the dir containing divoom_lib/ rather than counting
    // parents — the count changed when R66 made this a workspace crate
    // (target/ moved to the repo root). See crate::paths.
    let root = crate::paths::find_root_containing("divoom_lib")?;
    let candidate = root.join("divoom_lib").join("libdivoom_compact.dylib");
    if candidate.exists() {
        Some(candidate)
    } else {
        None
    }
}

// const u8* rgb, int w, int h, u16 time_ms, u8* out, int out_size -> int written
type EncodeFrameFn = unsafe extern "C" fn(*const u8, i32, i32, u16, *mut u8, i32) -> i32;
// const u8* rgb, int w, int h, u8* out, int out_size -> int written
type EncodeStaticFn = unsafe extern "C" fn(*const u8, i32, i32, *mut u8, i32) -> i32;

/// A loaded `libdivoom_compact` handle exposing the image encoders.
pub struct NativeEncoder {
    lib: Library,
}

impl NativeEncoder {
    /// Load the dylib by path. Returns an error if it can't be opened (the caller
    /// then uses the pure-Rust / Python-parity path instead).
    pub fn load<P: AsRef<OsStr>>(path: P) -> Result<Self, libloading::Error> {
        // SAFETY: loading a trusted, in-repo dylib we built; no init side effects.
        let lib = unsafe { Library::new(path)? };
        Ok(Self { lib })
    }

    /// Worst-case output buffer: header + 256*3 palette + 1 byte/pixel (8 bits/px).
    /// MUST match the C's conservative `worst_size` check (the under-allocation bug
    /// this session fixed: the buffer has to be `w*h`, not `(w*h+7)/8`).
    fn out_buf(w: i32, h: i32, header: usize) -> Vec<u8> {
        vec![0u8; header + 256 * 3 + (w as usize) * (h as usize)]
    }

    fn call_frame(
        &self,
        sym: &[u8],
        rgb: &[u8],
        w: i32,
        h: i32,
        time_ms: u16,
        header: usize,
    ) -> Option<Vec<u8>> {
        let mut out = Self::out_buf(w, h, header);
        let n = out.len() as i32;
        // SAFETY: rgb is w*h*3 bytes, out is sized to the C's worst case; the C
        // function writes at most `n` bytes and returns the count (or <0 on error).
        let rc = unsafe {
            let f: Symbol<EncodeFrameFn> = self.lib.get(sym).ok()?;
            f(rgb.as_ptr(), w, h, time_ms, out.as_mut_ptr(), n)
        };
        if rc < 0 {
            return None;
        }
        out.truncate(rc as usize);
        Some(out)
    }

    /// `divoom_encode_animation_frame` — one 0x49 frame body (7-byte header).
    pub fn encode_animation_frame(
        &self,
        rgb: &[u8],
        w: i32,
        h: i32,
        time_ms: u16,
    ) -> Option<Vec<u8>> {
        self.call_frame(b"divoom_encode_animation_frame", rgb, w, h, time_ms, 7)
    }

    /// `divoom_encode_animation_frame_32` — the 32x32 encoder (8-byte header).
    pub fn encode_animation_frame_32(
        &self,
        rgb: &[u8],
        w: i32,
        h: i32,
        time_ms: u16,
    ) -> Option<Vec<u8>> {
        self.call_frame(b"divoom_encode_animation_frame_32", rgb, w, h, time_ms, 8)
    }

    /// `divoom_encode_static_image` — single-image 0x44 body (7-byte header).
    pub fn encode_static_image(&self, rgb: &[u8], w: i32, h: i32) -> Option<Vec<u8>> {
        let mut out = Self::out_buf(w, h, 7);
        let n = out.len() as i32;
        // SAFETY: as above (no time_ms arg for the static encoder).
        let rc = unsafe {
            let f: Symbol<EncodeStaticFn> = self.lib.get(b"divoom_encode_static_image").ok()?;
            f(rgb.as_ptr(), w, h, out.as_mut_ptr(), n)
        };
        if rc < 0 {
            return None;
        }
        out.truncate(rc as usize);
        Some(out)
    }
}
