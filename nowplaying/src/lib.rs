//! nowplaying — what is playing on this Mac, with cover art as real bytes.
//!
//! # Why this crate exists
//!
//! divoom-control used to answer "what is playing?" twice: once in Python for
//! the GUI's preview card and once in Rust for the daemon's device push. Both
//! copies drove AppleScript at each player in turn, and when a player gave a
//! title but no cover they guessed a URL from the **iTunes Search API**. That
//! guess cannot resolve non-album content — YouTube Music, podcasts, live sets
//! — and needs a network round trip in order to fail.
//!
//! It also cost a TCC prompt per player. Reaching a player over Apple Events
//! requires an Automation grant, and a headless daemon's consent dialog has no
//! visible owner: the user never sees it, the event is denied, and the daemon
//! silently gets nothing while the foreground GUI works fine. Kaset was
//! addressed by both implementations and primed by neither, which is precisely
//! why its album art never reached the device.
//!
//! MediaRemote replaces all of it. One system-wide source, every player that
//! publishes to Now Playing, the exact image the player is displaying, and no
//! per-app grant.
//!
//! # The catch, established by probing rather than by reading docs
//!
//! Since macOS 15.4 the read API is entitlement-gated. On macOS 26.6.2 a direct
//! `dlopen` + `dlsym` from an ordinary process **succeeds** and then hands back
//! a NULL dictionary — it fails in the shape of an empty result, not an error.
//! `/usr/bin/perl` carries the entitlement, so the query runs inside perl via a
//! small dylib of ours (`native/np_helper.m`). That indirection is not
//! cleverness for its own sake; it is the only way in.
//!
//! Two consequences worth stating up front:
//!
//! * **The declared MIME lies.** MediaRemote reports `image/jpeg` while handing
//!   back TIFF bytes. Everything here sniffs the magic number instead.
//! * **Availability must be honest.** Apple can withdraw this at any release,
//!   so [`availability`] probes each prerequisite and names the one that failed
//!   rather than letting the feature vanish silently.

pub mod artwork;
pub mod availability;
pub mod track;

#[cfg(target_os = "macos")]
pub mod media_remote;

pub use artwork::{Artwork, ImageFormat};
pub use availability::Unavailable;
pub use track::Track;

/// The current track from the best available source, or `Ok(None)` when nothing
/// is playing.
///
/// Today that is MediaRemote alone: it covers every player that publishes to
/// Now Playing, which on this machine includes Kaset, Music, and Spotify.
/// Sources that do NOT publish there (a Navidrome client read through its own
/// API, say) belong behind this same function as additional providers.
#[cfg(target_os = "macos")]
pub fn current_track() -> Result<Option<Track>, String> {
    media_remote::current_track()
}

#[cfg(not(target_os = "macos"))]
pub fn current_track() -> Result<Option<Track>, String> {
    Err(Unavailable::NotMacOS.reason())
}

/// Why now-playing cannot work here, or `None` if it can.
pub fn unavailable() -> Option<Unavailable> {
    #[cfg(target_os = "macos")]
    {
        media_remote::unavailable()
    }
    #[cfg(not(target_os = "macos"))]
    {
        Some(Unavailable::NotMacOS)
    }
}
