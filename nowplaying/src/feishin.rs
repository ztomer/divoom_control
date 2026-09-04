//! Feishin (Navidrome / Subsonic) provider.
//!
//! # Why this exists alongside MediaRemote
//!
//! MediaRemote covers every player that publishes to the macOS Now Playing
//! source. Feishin is an Electron app and may or may not — which is exactly the
//! kind of thing that should not be assumed, so this provider is chained AFTER
//! MediaRemote: if MediaRemote reports the track, this never runs; if it does
//! not, a Feishin track still reaches the device.
//!
//! It reaches Feishin by a genuinely different mechanism, which is why it could
//! not simply be deleted along with the rest of the duplicate implementation:
//! it scrapes Feishin's cached Navidrome credentials out of its Electron
//! LevelDB store and asks the SERVER what is playing, over Subsonic.
//!
//! # This is fragile, and says so
//!
//! Reading another app's LevelDB by byte-scanning for `"credential":"` is not a
//! supported interface. Feishin can change its storage shape at any release and
//! this stops working. It therefore fails QUIETLY to `None` (no track) rather
//! than erroring — a broken scrape must not take down the whole now-playing
//! chain — while `unavailable()` still explains what is missing when asked.
//!
//! Recovered from `divoomd/src/live_jobs/music.rs` (deleted in R67 Phase 2)
//! rather than rewritten, so the hard-won details survive: the `f=json` query
//! parameters, the single-vs-array `entry` shape, and the cover-art URL form.

use std::path::PathBuf;
use std::time::Duration;

use crate::artwork::Artwork;
use crate::track::Track;

const HTTP_TIMEOUT: Duration = Duration::from_secs(5);
/// Subsonic API identity. `v` is the protocol version, `c` the client name.
const SUBSONIC_ARGS: &str = "f=json&c=divoom&v=1.16.0";

/// Why Feishin cannot be queried, or `None` if it can.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FeishinUnavailable {
    NotRunning,
    NoStore(PathBuf),
    NoCredentials,
}

impl FeishinUnavailable {
    pub fn reason(&self) -> String {
        match self {
            Self::NotRunning => "Feishin is not running".into(),
            Self::NoStore(p) => format!("Feishin's local storage was not found at {}", p.display()),
            Self::NoCredentials => "no cached Navidrome credentials in Feishin's local storage \
                 (sign in to Feishin once)"
                .into(),
        }
    }
}

/// Feishin's own config file.
fn config_path() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    Some(PathBuf::from(home).join("Library/Application Support/Feishin/config.json"))
}

/// Has the user enabled Feishin's Media Session integration?
///
/// # Why this matters more than anything else in this file
///
/// Feishin publishes to macOS Now Playing only when its `mediaSession` setting
/// is ON. With it OFF, Feishin never registers as a Now Playing client — it is
/// invisible to MediaRemote no matter how loudly it is playing, which is
/// exactly what made it look unreachable (verified 2026-08-29: the client
/// registry listed Kaset twice and Feishin not at all, and Feishin's config
/// read `"mediaSession": false`).
///
/// Turning it ON is strictly better than everything this module does: MediaRemote
/// then supplies the track AND the real cover-art bytes, with no credential
/// scraping and no dependency on the server's scrobble state. So when Feishin is
/// running with the setting off, that is worth SAYING rather than silently
/// falling back to the weaker path.
///
/// `None` when the config cannot be read — absence of evidence, not evidence of
/// absence.
pub fn media_session_enabled() -> Option<bool> {
    let text = std::fs::read_to_string(config_path()?).ok()?;
    let cfg: serde_json::Value = serde_json::from_str(&text).ok()?;
    cfg.get("mediaSession").and_then(|v| v.as_bool())
}

/// A one-line, ACTIONABLE hint when Feishin is running but cannot be seen
/// through Now Playing. `None` when there is nothing useful to say.
pub fn hint() -> Option<String> {
    if !is_running() {
        return None;
    }
    match media_session_enabled() {
        Some(false) => Some(
            "Feishin is running but its Media Session setting is OFF, so macOS \
             cannot see what it is playing. Enable it in Feishin's settings \
             (Settings > General > Media Session) to get track info and cover \
             art automatically."
                .to_string(),
        ),
        _ => None,
    }
}

fn store_dir() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    Some(PathBuf::from(home).join("Library/Application Support/Feishin/Local Storage/leveldb"))
}

/// Is a Feishin process alive?
///
/// Cheap gate before touching the filesystem: stale credentials from a closed
/// Feishin would otherwise let us report a "now playing" track from a server
/// the user is no longer listening through.
fn is_running() -> bool {
    std::process::Command::new("/usr/bin/pgrep")
        .arg("-q")
        .arg("Feishin")
        .status()
        .ok()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

/// Scrape `(server_url, auth_query_string)` out of Feishin's LevelDB files.
///
/// LevelDB is not parsed — the values are found by scanning for their JSON keys
/// in the raw `.ldb`/`.log` bytes. Crude, and deliberately so: a real LevelDB
/// reader would be a dependency and a lock-contention problem against a running
/// app, for a value that is a plain string.
fn find_credentials() -> Result<(String, String), FeishinUnavailable> {
    let dir = store_dir().ok_or(FeishinUnavailable::NoCredentials)?;
    if !dir.is_dir() {
        return Err(FeishinUnavailable::NoStore(dir));
    }
    let mut server_url = None;
    let mut auth_qs = None;

    let entries = std::fs::read_dir(&dir).map_err(|_| FeishinUnavailable::NoStore(dir.clone()))?;
    for entry in entries.flatten() {
        let path = entry.path();
        let ext = path.extension().and_then(|s| s.to_str()).unwrap_or("");
        if ext != "ldb" && ext != "log" {
            continue;
        }
        let Ok(data) = std::fs::read(&path) else {
            continue;
        };
        if auth_qs.is_none() {
            if let Some(idx) = find_subsequence(&data, b"\"credential\":\"") {
                let start = idx + 14;
                if let Some(end) = data[start..].iter().position(|&b| b == b'"') {
                    if let Ok(s) = std::str::from_utf8(&data[start..start + end]) {
                        // Feishin stores the full Subsonic auth query
                        // ("u=...&t=...&s=..."), so it is used verbatim.
                        if s.starts_with("u=") {
                            auth_qs = Some(s.to_string());
                        }
                    }
                }
            }
        }
        if server_url.is_none() {
            if let Some(idx) = find_subsequence(&data, b"\"url\":\"http") {
                let start = idx + 7;
                if let Some(end) = data[start..].iter().position(|&b| b == b'"') {
                    if let Ok(s) = std::str::from_utf8(&data[start..start + end]) {
                        server_url = Some(s.to_string());
                    }
                }
            }
        }
        if auth_qs.is_some() && server_url.is_some() {
            break;
        }
    }

    match (server_url, auth_qs) {
        (Some(url), Some(qs)) => Ok((url, qs)),
        _ => Err(FeishinUnavailable::NoCredentials),
    }
}

pub fn unavailable() -> Option<FeishinUnavailable> {
    if !is_running() {
        return Some(FeishinUnavailable::NotRunning);
    }
    find_credentials().err()
}

/// Parse a Subsonic `getNowPlaying` response into a `Track` (without artwork).
///
/// Split out so the response shape is testable without a server — including the
/// detail that `entry` is a bare object when one client is playing and an array
/// when several are.
pub fn parse_now_playing(
    body: &serde_json::Value,
) -> Option<(String, Option<String>, Option<String>)> {
    let sr = body.get("subsonic-response")?;
    if sr.get("status")?.as_str()? != "ok" {
        return None;
    }
    let entries = sr.get("nowPlaying")?.get("entry")?;
    let entry = if entries.is_array() {
        entries.as_array()?.first()?
    } else {
        entries
    };
    let title = entry.get("title")?.as_str()?.to_string();
    let artist = entry
        .get("artist")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let cover_art = entry
        .get("coverArt")
        .and_then(|v| v.as_str())
        .map(str::to_string);
    Some((title, artist, cover_art))
}

/// The current Feishin track, or `None` when nothing is playing / unavailable.
pub fn current_track() -> Option<Track> {
    if unavailable().is_some() {
        return None;
    }
    let (server_url, auth_qs) = find_credentials().ok()?;

    let client = reqwest::blocking::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .ok()?;

    let url = format!("{server_url}/rest/getNowPlaying.view?{SUBSONIC_ARGS}&{auth_qs}");
    let body: serde_json::Value = client.get(&url).send().ok()?.json().ok()?;
    let (title, artist, cover_art) = parse_now_playing(&body)?;

    // Artwork is fetched as BYTES here rather than handed on as a URL. A URL
    // would put the burden of auth, TLS and the file:// origin problem on every
    // consumer — and it is a URL that leaks the Subsonic credentials in its
    // query string, which has no business travelling further than this function.
    let artwork = cover_art.and_then(|id| {
        let art_url =
            format!("{server_url}/rest/getCoverArt.view?{SUBSONIC_ARGS}&id={id}&{auth_qs}");
        let resp = client.get(&art_url).send().ok()?;
        let declared = resp
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .map(str::to_string);
        let bytes = resp.bytes().ok()?.to_vec();
        (!bytes.is_empty()).then(|| Artwork::new(bytes, declared))
    });

    Some(Track {
        title: Some(title),
        artist,
        album: None,
        source: "Feishin".to_string(),
        artwork,
        // Subsonic's getNowPlaying only lists ACTIVE playback, so a result here
        // is by definition playing.
        is_playing: true,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_a_single_entry_object() {
        let body = json!({"subsonic-response": {"status": "ok", "nowPlaying": {
            "entry": {"title": "Solar", "artist": "The Present Sound", "coverArt": "al-42"}}}});
        let (title, artist, cover) = parse_now_playing(&body).expect("a track");
        assert_eq!(title, "Solar");
        assert_eq!(artist.as_deref(), Some("The Present Sound"));
        assert_eq!(cover.as_deref(), Some("al-42"));
    }

    #[test]
    fn parses_an_entry_array_and_takes_the_first() {
        // Subsonic returns an ARRAY when several clients are playing, and a bare
        // object when one is. Handling only one shape silently drops the other.
        let body = json!({"subsonic-response": {"status": "ok", "nowPlaying": {
            "entry": [{"title": "First"}, {"title": "Second"}]}}});
        let (title, _, _) = parse_now_playing(&body).expect("a track");
        assert_eq!(title, "First");
    }

    #[test]
    fn a_failed_subsonic_status_is_no_track() {
        let body = json!({"subsonic-response": {"status": "failed",
            "error": {"code": 40, "message": "Wrong username or password"}}});
        assert!(parse_now_playing(&body).is_none());
    }

    #[test]
    fn nothing_playing_is_no_track() {
        let body = json!({"subsonic-response": {"status": "ok", "nowPlaying": {}}});
        assert!(parse_now_playing(&body).is_none());
    }

    #[test]
    fn an_entry_without_a_title_is_not_a_track() {
        let body = json!({"subsonic-response": {"status": "ok", "nowPlaying": {
            "entry": {"artist": "Someone"}}}});
        assert!(parse_now_playing(&body).is_none());
    }

    #[test]
    fn an_empty_artist_is_treated_as_absent() {
        let body = json!({"subsonic-response": {"status": "ok", "nowPlaying": {
            "entry": {"title": "X", "artist": ""}}}});
        let (_, artist, _) = parse_now_playing(&body).unwrap();
        assert!(artist.is_none());
    }

    #[test]
    fn garbage_never_panics() {
        for body in [
            json!(null),
            json!([]),
            json!({"subsonic-response": 3}),
            json!({"subsonic-response": {"status": "ok"}}),
        ] {
            assert!(parse_now_playing(&body).is_none());
        }
    }

    #[test]
    fn credential_scanning_finds_values_in_raw_bytes() {
        // The scrape is a byte scan, so pin the exact key shapes it depends on:
        // if Feishin changes them this is the test that says so.
        let blob =
            br#"junk{"url":"https://music.example.com","credential":"u=me&t=abc&s=xyz"}junk"#;
        let url_idx = find_subsequence(blob, b"\"url\":\"http").expect("url key");
        let cred_idx = find_subsequence(blob, b"\"credential\":\"").expect("credential key");
        let url_start = url_idx + 7;
        let url_end = blob[url_start..].iter().position(|&b| b == b'"').unwrap();
        assert_eq!(
            &blob[url_start..url_start + url_end],
            b"https://music.example.com"
        );
        let cred_start = cred_idx + 14;
        let cred_end = blob[cred_start..].iter().position(|&b| b == b'"').unwrap();
        assert_eq!(
            &blob[cred_start..cred_start + cred_end],
            b"u=me&t=abc&s=xyz"
        );
    }

    #[test]
    fn the_hint_is_actionable_when_media_session_is_off() {
        // A diagnostic the user cannot act on is barely better than silence, so
        // the hint must name the setting AND where to find it.
        if !is_running() {
            return; // nothing to hint about
        }
        if media_session_enabled() == Some(false) {
            let h = hint().expect("a hint when the setting is off");
            assert!(h.contains("Media Session"), "must name the setting: {h}");
            assert!(h.contains("Settings"), "must say where to find it: {h}");
        }
    }

    #[test]
    fn every_unavailable_reason_is_a_sentence() {
        for u in [
            FeishinUnavailable::NotRunning,
            FeishinUnavailable::NoStore(PathBuf::from("/x")),
            FeishinUnavailable::NoCredentials,
        ] {
            assert!(u.reason().len() > 15, "too terse: {}", u.reason());
        }
    }
}
