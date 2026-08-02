//! Now-playing track discovery for the music live-job: Feishin (Navidrome),
//! Kaset, Spotify, Apple Music (macOS), plus iTunes album-art lookup.

use std::time::Duration;

pub(super) struct TrackInfo {
    pub(super) track: String,
    pub(super) artist: String,
    pub(super) _source: String,
    pub(super) artwork_url: Option<String>,
}

fn get_feishin_running() -> bool {
    std::process::Command::new("pgrep")
        .arg("-q")
        .arg("Feishin")
        .status()
        .ok()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn find_feishin_creds() -> Option<(String, String)> {
    let home = std::env::var("HOME").ok()?;
    let path = std::path::PathBuf::from(home)
        .join("Library/Application Support/Feishin/Local Storage/leveldb");
    if !path.is_dir() {
        return None;
    }
    let mut server_url = None;
    let mut auth_qs = None;

    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            let fpath = entry.path();
            let ext = fpath.extension().and_then(|s| s.to_str()).unwrap_or("");
            if ext == "ldb" || ext == "log" {
                if let Ok(data) = std::fs::read(&fpath) {
                    if auth_qs.is_none() {
                        if let Some(idx) = find_subsequence(&data, b"\"credential\":\"") {
                            let start = idx + 14;
                            if let Some(end) = data[start..].iter().position(|&b| b == b'"') {
                                if let Ok(s) = std::str::from_utf8(&data[start..start + end]) {
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
            }
        }
    }

    match (server_url, auth_qs) {
        (Some(url), Some(qs)) => Some((url, qs)),
        _ => None,
    }
}

fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

async fn get_feishin_playing_track(client: &reqwest::Client) -> Option<TrackInfo> {
    if !get_feishin_running() {
        return None;
    }
    let (server_url, auth_qs) = find_feishin_creds()?;
    let api_url = format!(
        "{}/rest/getNowPlaying.view?f=json&c=divoom&v=1.16.0&{}",
        server_url, auth_qs
    );

    let res = client
        .get(&api_url)
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .ok()?;
    let body: serde_json::Value = res.json().await.ok()?;
    let sr = body.get("subsonic-response")?;
    if sr.get("status")?.as_str()? != "ok" {
        return None;
    }
    let np = sr.get("nowPlaying")?;
    let entries = np.get("entry")?;
    let entry = if entries.is_array() {
        entries.as_array()?.first()?
    } else {
        entries
    };
    let title = entry.get("title")?.as_str()?.to_string();
    let artist = entry
        .get("artist")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let cover_art = entry.get("coverArt").and_then(|v| v.as_str());
    let artwork_url = cover_art.map(|id| {
        format!(
            "{}/rest/getCoverArt.view?f=json&c=divoom&v=1.16.0&id={}&{}",
            server_url, id, auth_qs
        )
    });
    Some(TrackInfo {
        track: title,
        artist,
        _source: "Feishin".to_string(),
        artwork_url,
    })
}

async fn get_kaset_playing_track() -> Option<TrackInfo> {
    let script = r#"
    if application "Kaset" is running then
        tell application "Kaset"
            set infoJson to get player info
            if infoJson is not "" then
                return infoJson
            end if
        end tell
    end if
    return ""
    "#;
    let output = std::process::Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output()
        .ok()?;
    let raw = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if raw.is_empty() {
        return None;
    }
    let info: serde_json::Value = serde_json::from_str(&raw).ok()?;
    if info.get("isPlaying")?.as_bool()? {
        let ct = info.get("currentTrack")?;
        let name = ct.get("name")?.as_str()?;
        let artist = ct.get("artist").and_then(|v| v.as_str()).unwrap_or("");
        let artwork_url = ct
            .get("artworkURL")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        return Some(TrackInfo {
            track: name.to_string(),
            artist: artist.to_string(),
            _source: "Kaset".to_string(),
            artwork_url,
        });
    }
    None
}

async fn get_spotify_playing_track() -> Option<TrackInfo> {
    let script = r#"
    if application "Spotify" is running then
        tell application "Spotify"
            if player state is playing then
                return name of current track & " -|- " & artist of current track
            end if
        end tell
    end if
    return ""
    "#;
    let output = std::process::Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output()
        .ok()?;
    let raw = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if raw.contains(" -|- ") {
        let parts: Vec<&str> = raw.split(" -|- ").collect();
        return Some(TrackInfo {
            track: parts[0].to_string(),
            artist: parts[1].to_string(),
            _source: "Spotify".to_string(),
            artwork_url: None,
        });
    }
    None
}

async fn get_music_playing_track() -> Option<TrackInfo> {
    let script = r#"
    if application "Music" is running then
        tell application "Music"
            if player state is playing then
                return name of current track & " -|- " & artist of current track
            end if
        end tell
    end if
    return ""
    "#;
    let output = std::process::Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output()
        .ok()?;
    let raw = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if raw.contains(" -|- ") {
        let parts: Vec<&str> = raw.split(" -|- ").collect();
        return Some(TrackInfo {
            track: parts[0].to_string(),
            artist: parts[1].to_string(),
            _source: "Apple Music".to_string(),
            artwork_url: None,
        });
    }
    None
}

pub(super) async fn get_current_playing_track(client: &reqwest::Client) -> Option<TrackInfo> {
    if cfg!(target_os = "macos") {
        if let Some(t) = get_feishin_playing_track(client).await {
            return Some(t);
        }
        if let Some(t) = get_kaset_playing_track().await {
            return Some(t);
        }
        if let Some(t) = get_spotify_playing_track().await {
            return Some(t);
        }
        if let Some(t) = get_music_playing_track().await {
            return Some(t);
        }
    }
    None
}

pub(super) async fn fetch_album_art_url(
    client: &reqwest::Client,
    track: &str,
    artist: &str,
) -> Option<String> {
    let term = format!("{} {}", artist, track);
    let res = client
        .get("https://itunes.apple.com/search")
        .query(&[("term", term.as_str()), ("limit", "1"), ("entity", "song")])
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .ok()?;
    let body: serde_json::Value = res.json().await.ok()?;
    let results = body.get("results")?.as_array()?;
    if !results.is_empty() {
        let artwork_url = results[0].get("artworkUrl100")?.as_str()?;
        return Some(artwork_url.replace("100x100bb", "500x500bb"));
    }
    None
}
