//! Album artwork bytes, with the format determined by LOOKING at them.
//!
//! # Never trust the declared MIME
//!
//! MediaRemote reports `kMRMediaRemoteNowPlayingInfoArtworkMIMEType`, and on
//! macOS 26.6.2 that field says `image/jpeg` while the bytes it hands back
//! begin `4d 4d 00 2a` — big-endian TIFF. Measured on a live track
//! (2026-08-29), 1,187,190 bytes.
//!
//! A decoder chosen from the declared type would therefore be handed a TIFF and
//! told it is a JPEG. Every consumer here sniffs the magic number instead, and
//! the declared value is carried only so a human can see the discrepancy.

/// An image format we can recognise from its first bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImageFormat {
    Jpeg,
    Png,
    Gif,
    TiffBigEndian,
    TiffLittleEndian,
    Bmp,
    Webp,
    /// Recognised as none of the above. Carried rather than rejected: a decoder
    /// may still cope, and silently dropping artwork is worse than trying.
    Unknown,
}

impl ImageFormat {
    /// Identify a format from the leading magic bytes.
    pub fn sniff(bytes: &[u8]) -> Self {
        const SIGS: &[(&[u8], ImageFormat)] = &[
            (&[0xFF, 0xD8, 0xFF], ImageFormat::Jpeg),
            (b"\x89PNG\r\n\x1a\n", ImageFormat::Png),
            (b"GIF87a", ImageFormat::Gif),
            (b"GIF89a", ImageFormat::Gif),
            (b"MM\x00\x2a", ImageFormat::TiffBigEndian),
            (b"II\x2a\x00", ImageFormat::TiffLittleEndian),
            (b"BM", ImageFormat::Bmp),
        ];
        for (sig, fmt) in SIGS {
            if bytes.starts_with(sig) {
                return *fmt;
            }
        }
        // RIFF....WEBP — the marker is at offset 8, not 0.
        if bytes.len() >= 12 && bytes.starts_with(b"RIFF") && &bytes[8..12] == b"WEBP" {
            return ImageFormat::Webp;
        }
        ImageFormat::Unknown
    }

    /// The MIME type this format ACTUALLY is.
    pub fn mime(self) -> &'static str {
        match self {
            Self::Jpeg => "image/jpeg",
            Self::Png => "image/png",
            Self::Gif => "image/gif",
            Self::TiffBigEndian | Self::TiffLittleEndian => "image/tiff",
            Self::Bmp => "image/bmp",
            Self::Webp => "image/webp",
            Self::Unknown => "application/octet-stream",
        }
    }

    /// The conventional extension, for writing artwork to a temp file.
    pub fn extension(self) -> &'static str {
        match self {
            Self::Jpeg => "jpg",
            Self::Png => "png",
            Self::Gif => "gif",
            Self::TiffBigEndian | Self::TiffLittleEndian => "tiff",
            Self::Bmp => "bmp",
            Self::Webp => "webp",
            Self::Unknown => "bin",
        }
    }
}

/// Cover art as bytes, not as a URL.
///
/// The whole point of this crate: the old path guessed an artwork URL from the
/// track name via the iTunes Search API, which cannot resolve non-album content
/// (YouTube Music, podcasts, live sets) and needs a network round trip to fail.
/// MediaRemote hands over the exact image the player is displaying.
#[derive(Debug, Clone)]
pub struct Artwork {
    pub bytes: Vec<u8>,
    /// Determined by sniffing, and authoritative.
    pub format: ImageFormat,
    /// What the source CLAIMED, kept only for diagnostics. May disagree with
    /// `format`, and on macOS it routinely does.
    pub declared_mime: Option<String>,
}

impl Artwork {
    pub fn new(bytes: Vec<u8>, declared_mime: Option<String>) -> Self {
        let format = ImageFormat::sniff(&bytes);
        Self {
            bytes,
            format,
            declared_mime,
        }
    }

    pub fn len(&self) -> usize {
        self.bytes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.bytes.is_empty()
    }

    /// True when the source's declared MIME disagrees with the real bytes.
    /// Worth logging once: it means the source cannot be trusted for typing.
    pub fn mime_is_a_lie(&self) -> bool {
        match &self.declared_mime {
            Some(d) => !d.eq_ignore_ascii_case(self.format.mime()),
            None => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sniffs_the_formats_we_actually_receive() {
        assert_eq!(
            ImageFormat::sniff(&[0xFF, 0xD8, 0xFF, 0xE0]),
            ImageFormat::Jpeg
        );
        assert_eq!(
            ImageFormat::sniff(b"\x89PNG\r\n\x1a\n..."),
            ImageFormat::Png
        );
        assert_eq!(ImageFormat::sniff(b"GIF89a..."), ImageFormat::Gif);
        assert_eq!(
            ImageFormat::sniff(b"MM\x00\x2a\x00\x12"),
            ImageFormat::TiffBigEndian
        );
        assert_eq!(
            ImageFormat::sniff(b"II\x2a\x00"),
            ImageFormat::TiffLittleEndian
        );
        assert_eq!(ImageFormat::sniff(b"RIFF????WEBPVP8 "), ImageFormat::Webp);
        assert_eq!(ImageFormat::sniff(b"not an image"), ImageFormat::Unknown);
        assert_eq!(ImageFormat::sniff(&[]), ImageFormat::Unknown);
    }

    #[test]
    fn a_riff_that_is_not_webp_is_not_webp() {
        // RIFF is also WAV/AVI; the WEBP marker at offset 8 is what decides.
        assert_eq!(
            ImageFormat::sniff(b"RIFF????WAVEfmt "),
            ImageFormat::Unknown
        );
    }

    #[test]
    fn truncated_input_never_panics() {
        for n in 0..12 {
            let _ = ImageFormat::sniff(&b"RIFF????WEBP"[..n]);
            let _ = ImageFormat::sniff(&b"MM\x00\x2a"[..n.min(4)]);
        }
    }

    #[test]
    fn the_macos_mime_lie_is_detected() {
        // The exact case measured on macOS 26.6.2: declared image/jpeg, real
        // bytes are big-endian TIFF. If this ever stops being a lie the test
        // still passes for the right reason — it asserts on the disagreement,
        // not on Apple staying wrong.
        let art = Artwork::new(
            b"MM\x00\x2a\x00\x12\x10\x08".to_vec(),
            Some("image/jpeg".into()),
        );
        assert_eq!(art.format, ImageFormat::TiffBigEndian);
        assert_eq!(art.format.mime(), "image/tiff");
        assert!(art.mime_is_a_lie(), "declared jpeg, bytes are tiff");
    }

    #[test]
    fn an_honest_source_is_not_flagged() {
        let art = Artwork::new(vec![0xFF, 0xD8, 0xFF, 0xE0], Some("image/jpeg".into()));
        assert!(!art.mime_is_a_lie());
    }

    #[test]
    fn no_declared_mime_is_not_a_lie() {
        let art = Artwork::new(vec![0xFF, 0xD8, 0xFF], None);
        assert!(!art.mime_is_a_lie());
    }

    #[test]
    fn extensions_match_the_sniffed_format_not_the_claim() {
        let art = Artwork::new(b"MM\x00\x2a".to_vec(), Some("image/jpeg".into()));
        assert_eq!(art.format.extension(), "tiff");
    }
}
