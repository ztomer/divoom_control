//! The `now_playing` command — one source of truth for what is playing.
//!
//! R67/C2: the GUI used to answer this question itself, in Python, by driving
//! AppleScript at each player in turn and then guessing a cover-art URL from the
//! iTunes Search API. The daemon answered it a second time, in Rust, the same
//! way. Two implementations of one question, drifting apart, and the Python one
//! ran inside the GUI process — which is why the GUI was the thing asking for
//! Apple Music access.
//!
//! Now the daemon owns it and the GUI is a client. The daemon is also the right
//! owner for a second reason: it already holds the device, so the frame it
//! pushes and the frame the GUI previews can be the same bytes rather than two
//! lookalikes produced by different code.
//!
//! Artwork is only serialised when the caller asks for it. It is ~360 KB of
//! TIFF, and a live widget polling every few seconds does not want that on the
//! wire each time — it wants to notice `identity` changed and then fetch once.

use serde_json::{json, Value};

/// Handle `now_playing`.
///
/// Args:
///   * `include_artwork` (bool, default false) — attach base64 artwork bytes.
///
/// Reply shape is deliberately explicit about the three different "no track"
/// cases, because they need different UI: unavailable (say why), nothing
/// playing (idle), and an error (say what failed).
pub fn cmd_now_playing(args: &Value) -> Value {
    let include_artwork = args
        .get("include_artwork")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    #[cfg(target_os = "macos")]
    {
        if let Some(reason) = nowplaying::unavailable() {
            return json!({
                "success": true,
                "available": false,
                "playing": false,
                "reason": reason.reason(),
            });
        }
        match nowplaying::current_track() {
            Ok(None) => json!({"success": true, "available": true, "playing": false}),
            Ok(Some(track)) => track_to_json(&track, include_artwork),
            Err(e) => json!({
                "success": false,
                "available": true,
                "playing": false,
                "error": e,
            }),
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = include_artwork;
        json!({
            "success": true,
            "available": false,
            "playing": false,
            "reason": "now-playing metadata is only available on macOS",
        })
    }
}

#[cfg(target_os = "macos")]
fn track_to_json(track: &nowplaying::Track, include_artwork: bool) -> Value {
    use base64::Engine;

    let mut out = json!({
        "success": true,
        "available": true,
        "playing": true,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "source": track.source,
        // Change-detection key for clients: it deliberately EXCLUDES artwork
        // bytes, so the same song does not look new every poll.
        "identity": track.identity(),
        "display": track.display(),
        // Paused is not playing. MediaRemote keeps reporting a paused session's
        // track, so a UI that ignored this would show a stopped player as live
        // and a widget would push art for it.
        "is_playing": track.is_playing,
    });

    if let Some(art) = &track.artwork {
        out["artwork_bytes"] = json!(art.len());
        // The sniffed type, never the declared one — macOS says image/jpeg over
        // TIFF bytes, and a client that trusted that would pick the wrong
        // decoder.
        out["artwork_mime"] = json!(art.format.mime());
        if art.mime_is_a_lie() {
            out["artwork_mime_declared"] = json!(art.declared_mime);
        }
        if include_artwork {
            out["artwork_b64"] =
                json!(base64::engine::general_purpose::STANDARD.encode(&art.bytes));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn artwork_is_withheld_unless_asked_for() {
        // A live widget polls this; 360KB of base64 per tick is not free.
        let reply = cmd_now_playing(&json!({}));
        assert!(reply["success"].as_bool().unwrap_or(false) || reply.get("error").is_some());
        assert!(
            reply.get("artwork_b64").is_none(),
            "artwork must not ride along by default"
        );
    }

    #[test]
    fn the_reply_always_distinguishes_unavailable_from_idle() {
        // Three different "no track" states need three different UI responses;
        // collapsing them is how a dead feature looks identical to a quiet one.
        let reply = cmd_now_playing(&json!({}));
        assert!(reply.get("available").is_some(), "must state availability");
        assert!(
            reply.get("playing").is_some(),
            "must state whether a track is playing"
        );
        if reply["available"] == json!(false) {
            assert!(
                reply.get("reason").is_some(),
                "an unavailable source must say WHY"
            );
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn a_track_reply_carries_a_stable_identity() {
        use nowplaying::{Artwork, Track};
        let mut t = Track {
            title: Some("Solar".into()),
            artist: Some("The Present Sound".into()),
            album: None,
            source: "MediaRemote".into(),
            artwork: Some(Artwork::new(
                b"MM\x00\x2a".to_vec(),
                Some("image/jpeg".into()),
            )),
            is_playing: true,
        };
        let a = track_to_json(&t, false);
        t.artwork = Some(Artwork::new(b"MM\x00\x2aDIFFERENT".to_vec(), None));
        let b = track_to_json(&t, false);
        assert_eq!(
            a["identity"], b["identity"],
            "identity must not churn when only the cover bytes differ"
        );
        assert_eq!(
            a["artwork_mime"],
            json!("image/tiff"),
            "the SNIFFED type is reported, not the declared image/jpeg"
        );
        assert_eq!(
            a["artwork_mime_declared"],
            json!("image/jpeg"),
            "the lie is surfaced for diagnosis, not hidden"
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn include_artwork_attaches_the_bytes() {
        use nowplaying::{Artwork, Track};
        let t = Track {
            title: Some("X".into()),
            artist: None,
            album: None,
            source: "MediaRemote".into(),
            artwork: Some(Artwork::new(vec![0xFF, 0xD8, 0xFF, 0xE0], None)),
            is_playing: true,
        };
        let with = track_to_json(&t, true);
        assert!(with["artwork_b64"].as_str().is_some());
        let without = track_to_json(&t, false);
        assert!(without.get("artwork_b64").is_none());
        assert_eq!(
            without["artwork_bytes"],
            json!(4),
            "size is always reported so a client can decide to fetch"
        );
    }
}

#[cfg(all(test, target_os = "macos"))]
mod paused_tests {
    use super::*;
    use nowplaying::Track;

    fn track(is_playing: bool) -> Track {
        Track {
            title: Some("Golden Spires".into()),
            artist: Some("Mastodon".into()),
            album: None,
            source: "MediaRemote".into(),
            artwork: None,
            is_playing,
        }
    }

    #[test]
    fn the_reply_states_whether_it_is_actually_playing() {
        // MediaRemote goes on reporting a session's track after it is PAUSED
        // (PlaybackRate 0, measured on macOS 26.6.2). A UI that could not tell
        // the difference would show a stopped player as live.
        assert_eq!(
            track_to_json(&track(true), false)["is_playing"],
            json!(true)
        );
        assert_eq!(
            track_to_json(&track(false), false)["is_playing"],
            json!(false)
        );
    }

    #[test]
    fn a_paused_track_is_still_reported_not_hidden() {
        // Showing what is cued up beats showing nothing; the caller decides
        // whether to push it.
        let reply = track_to_json(&track(false), false);
        assert_eq!(reply["playing"], json!(true), "there IS a track");
        assert_eq!(reply["is_playing"], json!(false), "but it is paused");
        assert_eq!(reply["title"], json!("Golden Spires"));
    }
}
