//! The `MediaRemote` provider: perl-hosted helper, artwork as bytes.
//!
//! See `native/np_helper.m` for why this runs through `/usr/bin/perl`. In short:
//! since macOS 15.4 the read API is entitlement-gated, perl carries that
//! entitlement, and a dylib loaded into perl inherits it. Probed on macOS
//! 26.6.2 — direct dlopen returns a NULL dictionary, the perl path returns the
//! full record including artwork.
//!
//! Since 2026-09-12 the helper reads PER PLAYER: it asks every active player
//! for its playback state and reports the one that is playing, whoever holds
//! the elected session. The elected session is the fallback when nothing is.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use base64::Engine;

use crate::artwork::Artwork;
use crate::availability::{evaluate, framework_loads, Unavailable, PERL_PATH};
use crate::track::Track;

/// How long the helper gets before we give up. It runs one query and exits; a
/// slow answer means something is wrong, and a live-widget caller cannot afford
/// to block. The helper has its own 5s internal deadline, so this is the outer
/// bound.
const HELPER_TIMEOUT: Duration = Duration::from_secs(8);

/// `/usr/bin/arch`, used to pin the helper host's architecture.
const ARCH_PATH: &str = "/usr/bin/arch";

/// Locate the helper dylib and its perl loader.
///
/// Resolution order, first hit wins:
///   1. `NOWPLAYING_HELPER_DIR` — explicit override, for tests and packaging
///   2. next to the running executable, then in a sibling `bin/` — the shipped
///      layout, where the app bundle carries the helper
///   3. the crate's own `native/` directory — the development checkout
///
/// This mirrors how the repo already resolves `libdivoom_compact`: search for a
/// marker rather than counting parent directories, because a fixed parent count
/// silently broke when the build layout changed (see `divoomd/src/paths.rs`).
#[must_use]
pub fn locate_helper() -> Option<(PathBuf, PathBuf)> {
    let candidates = helper_search_dirs();
    for dir in candidates {
        let dylib = dir.join("libnp_helper.dylib");
        let loader = dir.join("np_load.pl");
        if dylib.is_file() && loader.is_file() {
            // ABSOLUTE paths only. perl is a hardened binary, and dlopen inside
            // one rejects a relative path outright ("relative path not allowed
            // in hardened program") — a confusing failure a caller would have
            // no way to interpret.
            let dylib = dylib.canonicalize().unwrap_or(dylib);
            let loader = loader.canonicalize().unwrap_or(loader);
            return Some((dylib, loader));
        }
    }
    None
}

fn helper_search_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(explicit) = std::env::var("NOWPLAYING_HELPER_DIR") {
        dirs.push(PathBuf::from(explicit));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.to_path_buf());
            dirs.push(parent.join("bin"));
            // A PyInstaller bundle puts helpers under Contents/Frameworks/bin
            // while the launcher lives in Contents/MacOS.
            if let Some(contents) = parent.parent() {
                dirs.push(contents.join("Frameworks").join("bin"));
            }
        }
    }
    dirs.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("native"));
    dirs
}

/// Why this provider cannot run right now, or `None` if it can.
#[must_use]
pub fn unavailable() -> Option<Unavailable> {
    let helper = locate_helper().map(|(dylib, _)| dylib);
    evaluate(
        cfg!(target_os = "macos"),
        framework_loads(),
        Path::new(PERL_PATH).is_file(),
        helper.as_deref(),
    )
}

/// Parse the helper's single JSON line into a `Track`.
///
/// Split from the process handling so the wire format is testable without
/// macOS, perl, or a playing track — the shape of this JSON is a contract
/// between two files in this crate, and contracts deserve tests.
///
/// # Errors
///
/// When the helper reported an error on the line instead of a track.
pub fn parse_helper_output(line: &str) -> Result<Option<Track>, String> {
    let v: serde_json::Value =
        serde_json::from_str(line.trim()).map_err(|e| format!("helper emitted non-JSON: {e}"))?;

    if !v
        .get("ok")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
    {
        let err = v
            .get("error")
            .and_then(|s| s.as_str())
            .unwrap_or("unknown helper error");
        return Err(err.to_string());
    }
    if !v
        .get("playing")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
    {
        return Ok(None);
    }

    let text = |key: &str| -> Option<String> {
        v.get(key)
            .and_then(|s| s.as_str())
            .map(str::to_string)
            .filter(|s| !s.is_empty())
    };

    let artwork = v
        .get("artwork_b64")
        .and_then(|s| s.as_str())
        .and_then(|b64| base64::engine::general_purpose::STANDARD.decode(b64).ok())
        .filter(|bytes| !bytes.is_empty())
        .map(|bytes| Artwork::new(bytes, text("artwork_mime_declared")));

    // The helper's `state` is the framework's own playback state for the
    // player it chose (2026-09-12, per-player read); it outranks the rate,
    // which a player may omit. Without it, PlaybackRate 0 means paused:
    // MediaRemote goes on reporting a paused session's track indefinitely,
    // so without this a widget would push cover art for something nobody is
    // listening to.
    let is_playing = v.get("state").and_then(|s| s.as_str()).map_or_else(
        || {
            v.get("playback_rate")
                .and_then(serde_json::Value::as_f64)
                .is_none_or(|r| r > 0.0)
        },
        |state| state == "Playing",
    );

    let track = Track {
        title: text("title"),
        artist: text("artist"),
        album: text("album"),
        source: "MediaRemote".to_string(),
        artwork,
        is_playing,
    };
    // An EMPTY session is not a track. macOS hands the Now Playing session
    // to the last app that touched it, and a player that was opened and
    // never loaded anything (Apple Music, stopped) holds it with no title,
    // no artist, no art and rate 0. Reporting that as "a paused track with
    // no name" made the widget say nothing was playing at all (2026-09-12,
    // Kaset masked by Music; the per-player read now finds Kaset first, and
    // this guard covers the case where nothing is playing at all).
    if track.title.is_none() && track.artist.is_none() && track.artwork.is_none() {
        return Ok(None);
    }
    Ok(Some(track))
}

/// Query the current track. `Ok(None)` means nothing is playing.
///
/// # Errors
///
/// When the media helper cannot be located or run, and when it reports a reason
/// of its own -- which includes the platform refusing access. `Ok(None)` means
/// nothing is playing, which is not an error.
pub fn current_track() -> Result<Option<Track>, String> {
    if let Some(reason) = unavailable() {
        return Err(reason.reason());
    }
    let (dylib, loader) = locate_helper().ok_or("helper not found")?;

    let (output, stderr) = run_with_timeout(&mut helper_command(&loader, &dylib), HELPER_TIMEOUT)?;

    let stdout = String::from_utf8_lossy(&output);
    let line = stdout.lines().find(|l| l.trim_start().starts_with('{'));
    match line {
        Some(l) => parse_helper_output(l),
        // Report what perl SAID. Without this the only symptom was
        // "produced no JSON", which says nothing about why.
        None if !stderr.is_empty() => Err(format!("helper failed: {stderr}")),
        None => Err(format!(
            "helper produced no JSON and no error (got {} bytes)",
            stdout.len()
        )),
    }
}

/// Build the command that runs the helper, pinned to arm64.
///
/// `/usr/bin/perl` is a UNIVERSAL binary (`x86_64` + arm64e) and the slice macOS
/// picks depends on the launching process's architecture preference, which is
/// inherited and not obviously controllable. Running the same command from a
/// shell selected arm64, while the daemon — itself a native arm64 binary,
/// launched through `LaunchServices` — selected **`x86_64`**, and perl then refused
/// our arm64 dylib with "incompatible architecture (have 'arm64', need
/// '`x86_64`')". Nothing about the daemon says "run me under Rosetta"; the
/// preference simply travelled.
///
/// So the architecture is stated rather than inherited. The alternative — a fat
/// dylib — is against house policy: macOS is Apple silicon only here, and
/// shipping an `x86_64` slice nobody builds for or tests is exactly the
/// silently-untested-binary shape that policy exists to prevent.
///
/// If `/usr/bin/arch` is missing we fall back to invoking perl directly; that is
/// strictly better than failing outright, and the arch mismatch (if any) then
/// surfaces in the helper's stderr rather than as silence.
fn helper_command(loader: &Path, dylib: &Path) -> Command {
    helper_command_for(loader, dylib, "np_get")
}

/// The same entitled host, for any function the helper exports.
fn helper_command_for(loader: &Path, dylib: &Path, func: &str) -> Command {
    if Path::new(ARCH_PATH).is_file() {
        let mut cmd = Command::new(ARCH_PATH);
        cmd.arg("-arm64")
            .arg(PERL_PATH)
            .arg(loader)
            .arg(dylib)
            .arg(func);
        cmd
    } else {
        let mut cmd = Command::new(PERL_PATH);
        cmd.arg(loader).arg(dylib).arg(func);
        cmd
    }
}

/// Run one helper entry point and return its single JSON line.
fn run_helper(func: &str) -> Result<String, String> {
    if let Some(reason) = unavailable() {
        return Err(reason.reason());
    }
    let (dylib, loader) = locate_helper().ok_or("helper not found")?;
    let (output, stderr) = run_with_timeout(
        &mut helper_command_for(&loader, &dylib, func),
        HELPER_TIMEOUT,
    )?;
    let stdout = String::from_utf8_lossy(&output);
    match stdout.lines().find(|l| l.trim_start().starts_with('{')) {
        Some(l) => Ok(l.to_string()),
        None if !stderr.is_empty() => Err(format!("helper failed: {stderr}")),
        None => Err(format!(
            "helper produced no JSON and no error (got {} bytes)",
            stdout.len()
        )),
    }
}

/// Every app registered with macOS Now Playing.
///
/// Registration is NOT playback — it means the app could own the session. An
/// app absent from this list does not publish to Now Playing at all and can only
/// be reached by its own provider.
///
/// # Errors
///
/// As [`current_track`]: the helper is missing, cannot run, or reported a
/// reason.
pub fn registered_players() -> Result<Vec<crate::discovery::Player>, String> {
    crate::discovery::parse_players(&run_helper("np_players")?)
}

/// Run a command with a wall-clock bound, draining both pipes concurrently.
///
/// Three requirements, and the first version got two of them wrong:
///
/// 1. **Bounded.** `Command::output()` waits forever. The helper pumps a runloop
///    and could hang; a live widget calling this every few seconds must not
///    accumulate stuck perl processes, so the deadline kills the child.
/// 2. **stdout drained on another thread.** Reading it only after the child
///    exited deadlocked on every real track: cover art is ~1.6 MB of base64 and
///    the OS pipe buffer is 64 KB, so the helper blocked mid-write while we
///    waited for an exit that could not come. That one passes with any small
///    fixture and hangs only on real artwork — i.e. only in front of a user.
/// 3. **stderr CAPTURED, not discarded.** It went to /dev/null at first, and
///    when the helper failed under the daemon the only symptom was "produced no
///    JSON (got 0 bytes)" while perl had written a perfectly clear explanation
///    that we threw away.
fn run_with_timeout(cmd: &mut Command, timeout: Duration) -> Result<(Vec<u8>, String), String> {
    use std::io::Read;
    use std::process::Stdio;

    let mut child = cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("cannot run {PERL_PATH}: {e}"))?;

    let mut stdout = child.stdout.take().ok_or("helper stdout was not piped")?;
    let reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stdout.read_to_end(&mut buf);
        buf
    });
    let mut stderr_pipe = child.stderr.take();
    let err_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(e) = stderr_pipe.as_mut() {
            let _ = e.read_to_end(&mut buf);
        }
        String::from_utf8_lossy(&buf).trim().to_string()
    });

    let deadline = std::time::Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    // Kill the child so both pipes close and the reader threads
                    // can finish — otherwise we leak two threads per call.
                    let _ = child.kill();
                    let _ = child.wait();
                    let _ = reader.join();
                    let _ = err_reader.join();
                    return Err(format!("helper timed out after {}s", timeout.as_secs()));
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(e) => return Err(format!("waiting for helper: {e}")),
        }
    }

    let out = reader
        .join()
        .map_err(|_| "helper reader thread panicked".to_string())?;
    let err = err_reader.join().unwrap_or_default();
    Ok((out, err))
}

#[cfg(test)]
#[path = "media_remote_tests.rs"]
mod tests;
