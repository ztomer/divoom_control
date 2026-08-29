//! The MediaRemote provider: perl-hosted helper, artwork as bytes.
//!
//! See `native/np_helper.m` for why this runs through `/usr/bin/perl`. In short:
//! since macOS 15.4 the read API is entitlement-gated, perl carries that
//! entitlement, and a dylib loaded into perl inherits it. Probed on macOS
//! 26.6.2 — direct dlopen returns a NULL dictionary, the perl path returns the
//! full record including artwork.

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
pub fn parse_helper_output(line: &str) -> Result<Option<Track>, String> {
    let v: serde_json::Value =
        serde_json::from_str(line.trim()).map_err(|e| format!("helper emitted non-JSON: {e}"))?;

    if !v.get("ok").and_then(|b| b.as_bool()).unwrap_or(false) {
        let err = v
            .get("error")
            .and_then(|s| s.as_str())
            .unwrap_or("unknown helper error");
        return Err(err.to_string());
    }
    if !v.get("playing").and_then(|b| b.as_bool()).unwrap_or(false) {
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

    // PlaybackRate 0 means paused. MediaRemote goes on reporting a paused
    // session's track indefinitely, so without this a widget would push cover
    // art for something nobody is listening to.
    let is_playing = v
        .get("playback_rate")
        .and_then(|r| r.as_f64())
        .map(|r| r > 0.0)
        // Absent rate: assume playing rather than silently showing nothing.
        .unwrap_or(true);

    Ok(Some(Track {
        title: text("title"),
        artist: text("artist"),
        album: text("album"),
        source: "MediaRemote".to_string(),
        artwork,
        is_playing,
    }))
}

/// Query the current track. `Ok(None)` means nothing is playing.
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
/// `/usr/bin/perl` is a UNIVERSAL binary (x86_64 + arm64e) and the slice macOS
/// picks depends on the launching process's architecture preference, which is
/// inherited and not obviously controllable. Running the same command from a
/// shell selected arm64, while the daemon — itself a native arm64 binary,
/// launched through LaunchServices — selected **x86_64**, and perl then refused
/// our arm64 dylib with "incompatible architecture (have 'arm64', need
/// 'x86_64')". Nothing about the daemon says "run me under Rosetta"; the
/// preference simply travelled.
///
/// So the architecture is stated rather than inherited. The alternative — a fat
/// dylib — is against house policy: macOS is Apple silicon only here, and
/// shipping an x86_64 slice nobody builds for or tests is exactly the
/// silently-untested-binary shape that policy exists to prevent.
///
/// If `/usr/bin/arch` is missing we fall back to invoking perl directly; that is
/// strictly better than failing outright, and the arch mismatch (if any) then
/// surfaces in the helper's stderr rather than as silence.
fn helper_command(loader: &Path, dylib: &Path) -> Command {
    if Path::new(ARCH_PATH).is_file() {
        let mut cmd = Command::new(ARCH_PATH);
        cmd.arg("-arm64")
            .arg(PERL_PATH)
            .arg(loader)
            .arg(dylib)
            .arg("np_get");
        cmd
    } else {
        let mut cmd = Command::new(PERL_PATH);
        cmd.arg(loader).arg(dylib).arg("np_get");
        cmd
    }
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
mod tests {
    use super::*;
    use crate::artwork::ImageFormat;

    #[test]
    fn parses_a_full_record() {
        // The exact shape measured from the live helper on macOS 26.6.2.
        let line = r#"{"ok":true,"playing":true,"title":"Solar",
            "artist":"The Present Sound","album":"Solar",
            "artwork_mime_declared":"image/jpeg","artwork_b64":"TU0AKgAS"}"#;
        let t = parse_helper_output(line).unwrap().expect("a track");
        assert_eq!(t.title.as_deref(), Some("Solar"));
        assert_eq!(t.artist.as_deref(), Some("The Present Sound"));
        assert_eq!(t.album.as_deref(), Some("Solar"));
        let art = t.artwork.expect("artwork bytes");
        assert_eq!(
            art.format,
            ImageFormat::TiffBigEndian,
            "format comes from the BYTES, not the declared image/jpeg"
        );
        assert!(art.mime_is_a_lie());
    }

    #[test]
    fn nothing_playing_is_not_an_error() {
        assert_eq!(
            parse_helper_output(r#"{"ok":true,"playing":false}"#).unwrap(),
            None
        );
    }

    #[test]
    fn a_track_without_artwork_still_parses() {
        // Podcasts and streams often have metadata and no image.
        let t = parse_helper_output(
            r#"{"ok":true,"playing":true,"title":"Ep 12",
            "artist":null,"album":null,"artwork_mime_declared":null}"#,
        )
        .unwrap()
        .expect("a track");
        assert_eq!(t.title.as_deref(), Some("Ep 12"));
        assert!(t.artist.is_none());
        assert!(t.artwork.is_none());
    }

    #[test]
    fn empty_strings_are_treated_as_absent() {
        let t = parse_helper_output(r#"{"ok":true,"playing":true,"title":"X","artist":""}"#)
            .unwrap()
            .expect("a track");
        assert!(t.artist.is_none(), "an empty artist is no artist");
    }

    #[test]
    fn helper_errors_surface_with_their_reason() {
        let e = parse_helper_output(r#"{"ok":false,"error":"framework_unavailable"}"#).unwrap_err();
        assert_eq!(e, "framework_unavailable");
    }

    #[test]
    fn non_json_output_is_an_error_not_a_panic() {
        assert!(parse_helper_output("Segmentation fault").is_err());
        assert!(parse_helper_output("").is_err());
    }

    #[test]
    fn undecodable_artwork_is_dropped_not_fatal() {
        // Better a track with no cover than no track at all.
        let t = parse_helper_output(
            r#"{"ok":true,"playing":true,"title":"X","artwork_b64":"!!!not base64!!!"}"#,
        )
        .unwrap()
        .expect("a track");
        assert_eq!(t.title.as_deref(), Some("X"));
        assert!(t.artwork.is_none());
    }

    #[test]
    fn empty_artwork_is_no_artwork() {
        let t = parse_helper_output(r#"{"ok":true,"playing":true,"title":"X","artwork_b64":""}"#)
            .unwrap()
            .expect("a track");
        assert!(t.artwork.is_none());
    }

    #[test]
    fn the_helper_dir_override_is_searched_first() {
        std::env::set_var("NOWPLAYING_HELPER_DIR", "/tmp/np-override-probe");
        let dirs = helper_search_dirs();
        std::env::remove_var("NOWPLAYING_HELPER_DIR");
        assert_eq!(
            dirs.first().unwrap(),
            &PathBuf::from("/tmp/np-override-probe")
        );
    }

    #[test]
    fn the_dev_checkout_is_always_a_candidate() {
        let dirs = helper_search_dirs();
        assert!(
            dirs.iter().any(|d| d.ends_with("native")),
            "the crate's own native/ dir must be searchable in a dev build"
        );
    }

    #[test]
    fn output_larger_than_a_pipe_buffer_does_not_deadlock() {
        // THE regression. The first implementation read the child's stdout only
        // after it exited, so anything over the ~64KB OS pipe buffer wedged:
        // the child blocked mid-write, the parent waited for an exit that could
        // never come. Real cover art is ~1.6MB of base64, so this hung on every
        // actual track while passing with any small fixture.
        //
        // 1MB, well past any plausible buffer, with a timeout short enough that
        // a regression fails fast instead of stalling the suite.
        let mut cmd = Command::new("/bin/sh");
        cmd.arg("-c")
            .arg("yes ABCDEFGHIJKLMNOPQRSTUVWXYZ | head -c 1048576");
        let (out, _err) = run_with_timeout(&mut cmd, Duration::from_secs(10))
            .expect("must not deadlock on a large payload");
        assert_eq!(out.len(), 1_048_576, "the whole payload must be read");
    }

    #[test]
    fn a_hanging_child_is_killed_at_the_deadline() {
        // Without the kill, the reader thread would block on an open pipe
        // forever and we would leak one per call.
        let mut cmd = Command::new("/bin/sh");
        cmd.arg("-c").arg("sleep 30");
        let started = std::time::Instant::now();
        let err = run_with_timeout(&mut cmd, Duration::from_millis(300)).unwrap_err();
        assert!(err.contains("timed out"), "got: {err}");
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "the timeout must actually bound the call"
        );
    }
}

#[cfg(test)]
mod host_tests {
    use super::*;

    #[test]
    fn the_helper_host_is_pinned_to_arm64() {
        // Regression: /usr/bin/perl is universal, and the slice macOS chooses is
        // INHERITED from the launching process. The same command ran arm64 from
        // a shell and x86_64 from the daemon, where perl then refused our arm64
        // dylib. Stating the architecture is the fix; inheriting it is the bug.
        let cmd = helper_command(Path::new("/tmp/l.pl"), Path::new("/tmp/d.dylib"));
        if Path::new(ARCH_PATH).is_file() {
            assert_eq!(cmd.get_program(), ARCH_PATH);
            let args: Vec<_> = cmd
                .get_args()
                .map(|a| a.to_string_lossy().into_owned())
                .collect();
            assert_eq!(
                args.first().map(String::as_str),
                Some("-arm64"),
                "the host architecture must be stated, not inherited"
            );
            assert!(args.contains(&PERL_PATH.to_string()));
            assert!(args.contains(&"np_get".to_string()));
        } else {
            assert_eq!(
                cmd.get_program(),
                PERL_PATH,
                "without /usr/bin/arch, fall back rather than fail"
            );
        }
    }

    #[test]
    fn located_helper_paths_are_absolute() {
        // perl is hardened, and dlopen inside a hardened process rejects a
        // relative path with a message no caller could act on.
        if let Some((dylib, loader)) = locate_helper() {
            assert!(
                dylib.is_absolute(),
                "dylib path must be absolute: {dylib:?}"
            );
            assert!(
                loader.is_absolute(),
                "loader path must be absolute: {loader:?}"
            );
        }
    }
}
