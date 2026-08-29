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
pub mod feishin;
#[cfg(target_os = "macos")]
pub mod media_remote;

pub use artwork::{Artwork, ImageFormat};
pub use availability::Unavailable;
pub use track::Track;

/// The current track from the best available source, or `Ok(None)` when nothing
/// is playing.
///
/// # Provider order, and why the fallthrough is conditional
///
/// MediaRemote first: it covers every player that publishes to the system Now
/// Playing source, and it returns the exact artwork the player is displaying.
///
/// Feishin second, and ONLY when MediaRemote has nothing actively playing.
/// The subtlety that makes the condition necessary: MediaRemote keeps reporting
/// a session's track after it is PAUSED (measured on macOS 26.6.2), so a paused
/// player would otherwise mask a different app that really is playing. A paused
/// MediaRemote track is still returned when no other provider has anything —
/// showing what is cued up beats showing nothing — but it never wins over live
/// playback elsewhere.
#[cfg(target_os = "macos")]
pub fn current_track() -> Result<Option<Track>, String> {
    let from_media_remote = media_remote::current_track();

    if let Ok(Some(track)) = &from_media_remote {
        if track.is_playing {
            return from_media_remote;
        }
    }

    // MediaRemote has nothing, or only something paused.
    if let Some(track) = feishin::current_track() {
        return Ok(Some(track));
    }
    from_media_remote
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
