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

use crate::protocol::err_reply;

/// Handle `weather` — one reading, from the source the device is pushed.
///
/// R67/C2: the GUI used to fetch weather itself through
/// `divoom_lib/weather_provider.py` while the daemon fetched it again for the
/// device. Two fetches of one fact, and — because `location` was never passed
/// through — potentially two different cities. The daemon now answers, so the
/// card and the panel cannot disagree.
pub async fn cmd_weather(args: &Value) -> Value {
    let location = args
        .get("location")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let client = reqwest::Client::new();
    match crate::weather::fetch(&client, &location).await {
        Ok(info) => json!({
            "success": true,
            "temperature_c": info.temperature_c,
            "weather_type": info.weather as u8,
            "location": location,
        }),
        // Say WHY. A weather card that silently shows nothing is the exact
        // dead-but-green state this round has been about.
        Err(e) => json!({"success": false, "error": e}),
    }
}

/// Run a blocking now-playing probe OFF the async runtime.
///
/// # Why this is not optional
///
/// `nowplaying::current_track()` and `nowplaying::players()` are synchronous,
/// and on the Feishin path they build a `reqwest::blocking::Client`. That
/// client owns a private tokio runtime, and dropping a runtime from inside an
/// async context does not return an error — it PANICS, and the panic lands on a
/// runtime worker thread, which aborts the whole process:
///
/// ```text
/// thread 'tokio-rt-worker' panicked at tokio/src/runtime/blocking/shutdown.rs:
/// Cannot drop a runtime in a context where blocking is not allowed.
/// ```
///
/// So the daemon did not merely fail the request — it DIED, leaving its socket
/// file behind, and every subsequent client call got `Connection refused`.
/// Reproduced by opening the GUI: it asks `now_playing` on load, and the
/// Feishin path is taken whenever MediaRemote reports nothing playing or only
/// something paused, which is the ordinary idle case.
///
/// `live_jobs` already called this family through `spawn_blocking`; these two
/// command handlers did not. One entry point observed the rule and two skipped
/// it, which is why the crash was invisible to every test that exercised the
/// live job rather than the command.
///
/// Returning through here makes the offload the ONLY way in: both handlers are
/// `async` and hold no synchronous entry point a caller could reach past.
async fn blocking_now_playing<F>(f: F) -> Value
where
    F: FnOnce() -> Value + Send + 'static,
{
    match tokio::task::spawn_blocking(f).await {
        Ok(v) => v,
        // A panic inside the closure is now contained: the task dies, the
        // daemon does not, and the caller is told rather than dropped.
        Err(e) => err_reply(&format!("now-playing probe failed: {e}")),
    }
}

/// Handle `players` — who is out there, and who is actually playing.
///
/// R67: `now_playing` returns the ONE session macOS considers current, and
/// macOS keeps that session on a paused player. So a paused Kaset made a
/// playing Feishin look silent, and nothing in the reply could distinguish
/// "Feishin is not playing" from "Feishin was never visible". This separates
/// registration from playback and names the players.
pub async fn cmd_players(_args: &Value) -> Value {
    // OFFLOADED, and that is not optional -- see `blocking_now_playing`.
    // `nowplaying::players()` probes Feishin, which builds a
    // `reqwest::blocking::Client`.
    blocking_now_playing(players_blocking).await
}

fn players_blocking() -> Value {
    #[cfg(target_os = "macos")]
    {
        let players: Vec<Value> = nowplaying::players()
            .into_iter()
            .map(|p| {
                json!({
                    "id": p.id,
                    "name": p.name,
                    "via": match p.via {
                        nowplaying::discovery::Reach::MediaRemote => "media_remote",
                        nowplaying::discovery::Reach::OwnProvider => "own_provider",
                    },
                    // `null` means UNKNOWN, which is a different claim from
                    // `false`. The session carries no app identity, so with
                    // several registered players we cannot say which is playing.
                    "is_playing": p.is_playing,
                })
            })
            .collect();
        let mut out = json!({"success": true, "players": players});
        // An actionable hint beats a silent gap: Feishin only reaches Now
        // Playing when its Media Session setting is on.
        if let Some(h) = nowplaying::feishin::hint() {
            out["hint"] = json!(h);
        }
        out
    }
    #[cfg(not(target_os = "macos"))]
    {
        json!({"success": true, "players": [],
               "reason": "media players are only discoverable on macOS"})
    }
}

/// Handle `now_playing`.
///
/// Args:
///   * `include_artwork` (bool, default false) — attach base64 artwork bytes.
///
/// Reply shape is deliberately explicit about the three different "no track"
/// cases, because they need different UI: unavailable (say why), nothing
/// playing (idle), and an error (say what failed).
pub async fn cmd_now_playing(args: &Value) -> Value {
    let include_artwork = args
        .get("include_artwork")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    // OFFLOADED -- see `blocking_now_playing`.
    blocking_now_playing(move || now_playing_blocking(include_artwork)).await
}

fn now_playing_blocking(include_artwork: bool) -> Value {
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

    // These are `#[tokio::test]`, not `#[test]`, and that is load-bearing.
    // As plain sync tests they called `cmd_now_playing` with NO runtime
    // running -- the one context where dropping a nested runtime is legal --
    // so they exercised the crashing function and could never see the crash.
    #[tokio::test]
    async fn artwork_is_withheld_unless_asked_for() {
        // A live widget polls this; 360KB of base64 per tick is not free.
        let reply = cmd_now_playing(&json!({})).await;
        assert!(reply["success"].as_bool().unwrap_or(false) || reply.get("error").is_some());
        assert!(
            reply.get("artwork_b64").is_none(),
            "artwork must not ride along by default"
        );
    }

    #[tokio::test]
    async fn the_reply_always_distinguishes_unavailable_from_idle() {
        // Three different "no track" states need three different UI responses;
        // collapsing them is how a dead feature looks identical to a quiet one.
        let reply = cmd_now_playing(&json!({})).await;
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

    #[tokio::test]
    async fn a_nested_runtime_can_be_dropped_inside_the_offload() {
        // THE regression. `nowplaying`'s Feishin path builds a
        // `reqwest::blocking::Client`, which owns a private tokio runtime.
        // Dropping a runtime from an async context does not error -- it panics
        // on a runtime worker thread and ABORTS THE PROCESS, so the daemon died
        // and left its socket behind whenever the GUI asked what was playing
        // and nothing was actively playing.
        //
        // A nested runtime reproduces the mechanism exactly, with no network
        // and no Feishin install, so this is deterministic on every machine --
        // unlike the real trigger, which needs Feishin credentials present and
        // would therefore never fire in CI.
        //
        // If someone removes the `spawn_blocking`, this does not fail politely:
        // it aborts the test binary. That is the correct volume for a defect
        // that aborts the daemon.
        let reply = blocking_now_playing(|| {
            let rt = tokio::runtime::Builder::new_current_thread()
                .build()
                .expect("nested runtime");
            drop(rt);
            json!({"success": true, "dropped": true})
        })
        .await;
        assert_eq!(reply["dropped"], json!(true));
    }

    #[tokio::test]
    async fn a_panic_in_the_probe_is_reported_not_fatal() {
        // Containment, not just avoidance: whatever the probe does, the daemon
        // answers the client instead of vanishing mid-request.
        let reply = blocking_now_playing(|| panic!("probe exploded")).await;
        assert_eq!(reply["success"], json!(false));
        assert!(
            reply["error"]
                .as_str()
                .unwrap_or("")
                .contains("now-playing"),
            "the caller should be told which probe failed: {reply}"
        );
    }

    #[tokio::test]
    async fn players_survives_the_same_offload() {
        let reply = cmd_players(&json!({})).await;
        assert_eq!(reply["success"], json!(true));
        assert!(reply.get("players").is_some(), "must list players");
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
