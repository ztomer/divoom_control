//! Panel tiles: the frame a panel is showing, as a menu icon.
//!
//! The daemon broadcasts every live frame with its pixels (a PNG data URL on
//! the `activity` event) and keeps it on the panel's activity record, so
//! `DeviceView.preview` is the real picture. This decodes it once per change
//! (cached by the data URL string, so an unchanged frame costs a lookup) into
//! the RGBA `Icon` a menu row carries. Step 3 of the v0.37 plan.

use std::collections::HashMap;

use tray_icon::menu::Icon;

/// Menu icons are drawn at this many points a side; a 16x16 frame scaled
/// with nearest neighbour keeps its diodes.
const TILE_PX: u32 = 36;

#[derive(Default)]
pub struct TileCache {
    by_src: HashMap<String, Option<Icon>>,
}

impl TileCache {
    /// The icon for this preview, decoding it on first sight. `None` when the
    /// preview is absent or not a decodable PNG data URL (the row then shows
    /// text only, which is honest).
    pub fn icon_for(&mut self, preview: Option<&str>) -> Option<Icon> {
        let src = preview?;
        if let Some(cached) = self.by_src.get(src) {
            return cached.clone();
        }
        let icon = decode_data_url(src).and_then(|(rgba, w, h)| {
            let (rgba, w, h) = upscale_nearest(&rgba, w, h, TILE_PX);
            Icon::from_rgba(rgba, w, h).ok()
        });
        // Bound the cache: previews change every few seconds per panel.
        if self.by_src.len() > 64 {
            self.by_src.clear();
        }
        self.by_src.insert(src.to_string(), icon.clone());
        icon
    }
}

/// `data:image/png;base64,...` -> (RGBA bytes, width, height).
pub fn decode_data_url(src: &str) -> Option<(Vec<u8>, u32, u32)> {
    let b64 = src.strip_prefix("data:image/png;base64,")?;
    let bytes = base64_decode(b64)?;
    let img = image::load_from_memory_with_format(&bytes, image::ImageFormat::Png).ok()?;
    let rgba = img.to_rgba8();
    let (w, h) = rgba.dimensions();
    if w == 0 || h == 0 {
        return None;
    }
    Some((rgba.into_raw(), w, h))
}

/// Nearest-neighbour upscale to `target` points a side (integer factor when
/// the source divides it, else the nearest pixel). Diodes stay square.
fn upscale_nearest(rgba: &[u8], w: u32, h: u32, target: u32) -> (Vec<u8>, u32, u32) {
    if w >= target || h >= target {
        return (rgba.to_vec(), w, h);
    }
    // 64-bit only (house rule): the products fit usize with room to spare.
    let (tw, th, tt) = (w as usize, h as usize, target as usize);
    let mut out = Vec::with_capacity(tt * tt * 4);
    for y in 0..tt {
        let sy = y * th / tt;
        for x in 0..tt {
            let sx = x * tw / tt;
            let o = (sy * tw + sx) * 4;
            out.extend_from_slice(&rgba[o..o + 4]);
        }
    }
    (out, target, target)
}

/// Standard base64 (what the daemon emits), no external crate needed here.
fn base64_decode(s: &str) -> Option<Vec<u8>> {
    fn val(c: u8) -> Option<u32> {
        Some(match c {
            b'A'..=b'Z' => u32::from(c - b'A'),
            b'a'..=b'z' => u32::from(c - b'a') + 26,
            b'0'..=b'9' => u32::from(c - b'0') + 52,
            b'+' => 62,
            b'/' => 63,
            _ => return None,
        })
    }
    let bytes = s.trim_end_matches('=').as_bytes();
    let mut out = Vec::with_capacity(bytes.len() * 3 / 4);
    let mut acc: u32 = 0;
    let mut bits = 0;
    for &c in bytes {
        if c == b'\n' || c == b'\r' {
            continue;
        }
        acc = (acc << 6) | val(c)?;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((acc >> bits) & 0xFF) as u8);
        }
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    // The same alphabet the decoder reads.
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    fn base64_encode(bytes: &[u8]) -> String {
        let mut out = String::new();
        for chunk in bytes.chunks(3) {
            let triple = [
                chunk[0],
                *chunk.get(1).unwrap_or(&0),
                *chunk.get(2).unwrap_or(&0),
            ];
            let word =
                (u32::from(triple[0]) << 16) | (u32::from(triple[1]) << 8) | u32::from(triple[2]);
            out.push(ALPHABET[(word >> 18) as usize & 63] as char);
            out.push(ALPHABET[(word >> 12) as usize & 63] as char);
            out.push(if chunk.len() > 1 {
                ALPHABET[(word >> 6) as usize & 63] as char
            } else {
                '='
            });
            out.push(if chunk.len() > 2 {
                ALPHABET[word as usize & 63] as char
            } else {
                '='
            });
        }
        out
    }

    fn png_data_url(width: u32, height: u32, rgb: [u8; 3]) -> String {
        let mut img = image::RgbImage::new(width, height);
        for px in img.pixels_mut() {
            *px = image::Rgb(rgb);
        }
        let mut buf = std::io::Cursor::new(Vec::new());
        img.write_to(&mut buf, image::ImageFormat::Png).unwrap();
        format!("data:image/png;base64,{}", base64_encode(&buf.into_inner()))
    }

    #[test]
    fn a_frame_decodes_to_a_tile_of_its_colour() {
        let (rgba, w, h) = decode_data_url(&png_data_url(16, 16, [255, 0, 0])).expect("decodes");
        assert_eq!((w, h), (16, 16));
        assert_eq!(&rgba[..4], &[255, 0, 0, 255]);
        let (up, uw, uh) = upscale_nearest(&rgba, w, h, TILE_PX);
        assert_eq!((uw, uh), (TILE_PX, TILE_PX));
        assert_eq!(
            &up[..4],
            &[255, 0, 0, 255],
            "nearest keeps the diode colour exactly"
        );
    }

    #[test]
    fn a_non_png_or_absent_preview_is_no_tile() {
        assert!(decode_data_url("data:image/gif;base64,AAAA").is_none());
        assert!(decode_data_url("data:image/png;base64,!!!").is_none());
        let mut cache = TileCache::default();
        assert!(cache.icon_for(None).is_none());
        assert!(cache.icon_for(Some("nonsense")).is_none());
    }

    #[test]
    fn the_cache_decodes_once_per_source() {
        let mut cache = TileCache::default();
        let src = png_data_url(16, 16, [0, 0, 255]);
        assert!(cache.icon_for(Some(&src)).is_some());
        assert_eq!(cache.by_src.len(), 1);
        assert!(cache.icon_for(Some(&src)).is_some());
        assert_eq!(cache.by_src.len(), 1, "same source, no second decode");
    }
}
