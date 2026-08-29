//! Which media players exist, and which one is actually PLAYING.
//!
//! # The problem this solves
//!
//! `current_track()` asks macOS for THE now-playing session. macOS keeps that
//! session on a player after it has been paused, so a paused Kaset reports a
//! track indefinitely while a different app is genuinely playing. A caller that
//! reads only the session cannot tell the two apart, and concludes the other app
//! is silent.
//!
//! Worse, the session says nothing about apps that never register with Now
//! Playing at all. Measured on macOS 26.6.2: Kaset registers (twice — the app
//! and its WebKit GPU helper); **Feishin does not appear at all**. So no amount
//! of reading the session would ever surface a Feishin track, and the only way
//! to know that was to enumerate.
//!
//! Discovery therefore reports three separable facts per player:
//!   * it is REGISTERED with Now Playing (could own the session), and/or
//!   * it is REACHABLE by its own provider (Feishin's Subsonic path), and
//!   * it is PLAYING right now.
//!
//! A UI can then say "Kaset is paused, Feishin is playing" instead of showing
//! one stale track, and `current_track()` can prefer whoever is actually
//! playing.

use crate::track::Track;

/// One player we know about.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Player {
    /// Bundle id where known (MediaRemote clients), else a provider name.
    pub id: String,
    pub name: String,
    /// How we can reach it.
    pub via: Reach,
    /// Is it playing RIGHT NOW? `None` when we cannot tell — which is honest,
    /// and different from "no".
    pub is_playing: Option<bool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reach {
    /// Registered with macOS Now Playing; artwork and metadata come for free.
    MediaRemote,
    /// Not registered; reachable only by its own provider.
    OwnProvider,
}

/// Parse the helper's `np_players` output.
///
/// Split from the process handling so the wire format is testable without
/// macOS, perl, or a running player.
pub fn parse_players(line: &str) -> Result<Vec<Player>, String> {
    let v: serde_json::Value =
        serde_json::from_str(line.trim()).map_err(|e| format!("helper emitted non-JSON: {e}"))?;
    if !v.get("ok").and_then(|b| b.as_bool()).unwrap_or(false) {
        return Err(v
            .get("error")
            .and_then(|s| s.as_str())
            .unwrap_or("unknown helper error")
            .to_string());
    }
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for entry in v
        .get("players")
        .and_then(|p| p.as_array())
        .map(Vec::as_slice)
        .unwrap_or(&[])
    {
        let id = entry
            .get("bundle_id")
            .and_then(|s| s.as_str())
            .unwrap_or("")
            .to_string();
        let name = entry
            .get("name")
            .and_then(|s| s.as_str())
            .unwrap_or("")
            .to_string();
        if name.is_empty() && id.is_empty() {
            continue;
        }
        // An app registers more than once — Kaset appears as itself AND as
        // com.apple.WebKit.GPU, both named "Kaset". Reporting one player twice
        // would make a UI list look broken, so collapse on the display name.
        if !seen.insert(name.clone()) {
            continue;
        }
        out.push(Player {
            id,
            name,
            via: Reach::MediaRemote,
            is_playing: None,
        });
    }
    Ok(out)
}

/// Attribute the active session to a registered player, where that is possible.
///
/// # Why this is deliberately conservative
///
/// The session's info dictionary carries NO app identity on macOS 26.6.2
/// (verified by dumping every key), and the APIs that would name it —
/// `MRMediaRemoteGetNowPlayingApplicationDisplayName` and `...ApplicationPID` —
/// segfault when called. So the session cannot be matched to a client directly.
///
/// What IS sound: the session belongs to one of the registered clients. When
/// exactly ONE app is registered, the session is unambiguously its. With
/// several, attributing it would be a guess, and a guess rendered as fact is
/// worse than an honest "unknown" — a UI can say "something is playing" without
/// pinning it on the wrong app.
pub fn annotate_with_session(players: &mut [Player], session: Option<&Track>) {
    let Some(track) = session else { return };
    let registered: Vec<usize> = players
        .iter()
        .enumerate()
        .filter(|(_, p)| p.via == Reach::MediaRemote)
        .map(|(i, _)| i)
        .collect();
    if registered.len() == 1 {
        players[registered[0]].is_playing = Some(track.is_playing);
    }
    // Several registered apps: leave every one `None`. We know SOMETHING is
    // playing; we do not know which, and saying so is the honest answer.
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_the_measured_output() {
        // Exactly what the helper returned on macOS 26.6.2 with Kaset paused.
        let line = r#"{"ok":true,"players":[
            {"bundle_id":"com.sertacozercan.Kaset","name":"Kaset"},
            {"bundle_id":"com.apple.WebKit.GPU","name":"Kaset"}]}"#;
        let players = parse_players(line).unwrap();
        assert_eq!(players.len(), 1, "one app, not two registrations");
        assert_eq!(players[0].name, "Kaset");
        assert_eq!(players[0].via, Reach::MediaRemote);
        assert_eq!(players[0].is_playing, None, "registration is not playback");
    }

    #[test]
    fn distinct_apps_are_kept_apart() {
        let line = r#"{"ok":true,"players":[
            {"bundle_id":"a","name":"Kaset"},{"bundle_id":"b","name":"Music"}]}"#;
        let players = parse_players(line).unwrap();
        assert_eq!(players.len(), 2);
    }

    #[test]
    fn an_empty_registry_is_not_an_error() {
        // Nothing has ever played this boot: a legitimate state, not a failure.
        assert!(parse_players(r#"{"ok":true,"players":[]}"#)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn helper_errors_surface() {
        let e = parse_players(r#"{"ok":false,"error":"symbol_missing"}"#).unwrap_err();
        assert_eq!(e, "symbol_missing");
        assert!(parse_players("not json").is_err());
    }

    #[test]
    fn entries_without_any_identity_are_skipped() {
        let line = r#"{"ok":true,"players":[{"bundle_id":"","name":""},{"name":"Real"}]}"#;
        let players = parse_players(line).unwrap();
        assert_eq!(players.len(), 1);
        assert_eq!(players[0].name, "Real");
    }

    fn track(source: &str, is_playing: bool) -> Track {
        Track {
            title: Some("T".into()),
            artist: None,
            album: None,
            source: source.into(),
            artwork: None,
            is_playing,
        }
    }

    #[test]
    fn a_single_registered_player_gets_the_session() {
        // Unambiguous: the session must belong to the only registered app.
        let mut players = vec![Player {
            id: "a".into(),
            name: "Kaset".into(),
            via: Reach::MediaRemote,
            is_playing: None,
        }];
        annotate_with_session(&mut players, Some(&track("MediaRemote", false)));
        assert_eq!(
            players[0].is_playing,
            Some(false),
            "Kaset is the session, and paused"
        );
    }

    #[test]
    fn several_registered_players_stay_unknown_rather_than_guessed() {
        // The session carries no app identity, so attributing it here would be
        // a guess. A guess rendered as fact is worse than an honest unknown.
        let mut players = vec![
            Player {
                id: "a".into(),
                name: "Kaset".into(),
                via: Reach::MediaRemote,
                is_playing: None,
            },
            Player {
                id: "b".into(),
                name: "Music".into(),
                via: Reach::MediaRemote,
                is_playing: None,
            },
        ];
        annotate_with_session(&mut players, Some(&track("MediaRemote", true)));
        assert!(
            players.iter().all(|p| p.is_playing.is_none()),
            "neither app may be blamed for the session"
        );
    }

    #[test]
    fn own_provider_players_are_not_confused_with_the_session() {
        // Feishin's state comes from its own provider; the MediaRemote session
        // must never be attributed to it.
        let mut players = vec![
            Player {
                id: "a".into(),
                name: "Kaset".into(),
                via: Reach::MediaRemote,
                is_playing: None,
            },
            Player {
                id: "f".into(),
                name: "Feishin".into(),
                via: Reach::OwnProvider,
                is_playing: Some(false),
            },
        ];
        annotate_with_session(&mut players, Some(&track("MediaRemote", true)));
        assert_eq!(
            players[0].is_playing,
            Some(true),
            "the lone registered app owns it"
        );
        assert_eq!(
            players[1].is_playing,
            Some(false),
            "Feishin keeps its own answer"
        );
    }

    #[test]
    fn no_session_leaves_everything_unknown() {
        let mut players = vec![Player {
            id: "a".into(),
            name: "Kaset".into(),
            via: Reach::MediaRemote,
            is_playing: None,
        }];
        annotate_with_session(&mut players, None);
        assert_eq!(players[0].is_playing, None);
    }
}
