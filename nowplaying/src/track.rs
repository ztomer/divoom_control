//! The one shape every provider returns.

use crate::artwork::Artwork;

/// What is playing, and the cover art as bytes.
///
/// Every field except `source` is optional because real sources are partial:
/// a YouTube Music track may have no album, a podcast no artist, a stream
/// nothing but a title. A consumer must render what it has rather than
/// requiring a full record.
#[derive(Debug, Clone, PartialEq)]
pub struct Track {
    pub title: Option<String>,
    pub artist: Option<String>,
    pub album: Option<String>,
    /// Which provider produced this — shown in the UI so the user can tell
    /// where the data came from, and useful when two sources disagree.
    pub source: String,
    pub artwork: Option<Artwork>,
}

impl PartialEq for Artwork {
    /// Compare by content: two Artworks are the same if the bytes are.
    fn eq(&self, other: &Self) -> bool {
        self.bytes == other.bytes
    }
}

impl Track {
    /// A track with nothing identifiable in it is not worth reporting — it
    /// would render as an empty card that looks like a bug.
    pub fn is_empty(&self) -> bool {
        self.title.is_none() && self.artist.is_none() && self.album.is_none()
    }

    /// "Artist — Title", or whichever half exists.
    pub fn display(&self) -> String {
        match (&self.artist, &self.title) {
            (Some(a), Some(t)) => format!("{a} — {t}"),
            (None, Some(t)) => t.clone(),
            (Some(a), None) => a.clone(),
            (None, None) => self.album.clone().unwrap_or_default(),
        }
    }

    /// Stable identity for change detection: has the TRACK changed, ignoring
    /// artwork bytes and elapsed time? A live widget re-pushes on this, so it
    /// must not churn on every poll of the same song.
    pub fn identity(&self) -> String {
        format!(
            "{}\u{1}{}\u{1}{}",
            self.artist.as_deref().unwrap_or(""),
            self.title.as_deref().unwrap_or(""),
            self.album.as_deref().unwrap_or("")
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn track(artist: Option<&str>, title: Option<&str>, album: Option<&str>) -> Track {
        Track {
            title: title.map(str::to_string),
            artist: artist.map(str::to_string),
            album: album.map(str::to_string),
            source: "test".into(),
            artwork: None,
        }
    }

    #[test]
    fn display_handles_every_partial_record() {
        assert_eq!(track(Some("A"), Some("T"), None).display(), "A — T");
        assert_eq!(track(None, Some("T"), None).display(), "T");
        assert_eq!(track(Some("A"), None, None).display(), "A");
        assert_eq!(track(None, None, Some("Alb")).display(), "Alb");
        assert_eq!(track(None, None, None).display(), "");
    }

    #[test]
    fn identity_ignores_artwork_so_a_widget_does_not_churn() {
        let mut a = track(Some("A"), Some("T"), Some("Al"));
        let mut b = a.clone();
        a.artwork = Some(Artwork::new(vec![1, 2, 3], None));
        b.artwork = Some(Artwork::new(vec![9, 9, 9], None));
        assert_eq!(
            a.identity(),
            b.identity(),
            "same song with different cover bytes is still the same song"
        );
    }

    #[test]
    fn identity_distinguishes_tracks_that_share_a_title() {
        assert_ne!(
            track(Some("A"), Some("Solar"), None).identity(),
            track(Some("B"), Some("Solar"), None).identity()
        );
    }

    #[test]
    fn identity_cannot_be_forged_by_field_run_together() {
        // "AB" + "" must not collide with "A" + "B"; the separator is why.
        assert_ne!(
            track(Some("AB"), None, None).identity(),
            track(Some("A"), Some("B"), None).identity()
        );
    }

    #[test]
    fn an_all_empty_track_is_empty() {
        assert!(track(None, None, None).is_empty());
        assert!(!track(None, Some("T"), None).is_empty());
    }
}
