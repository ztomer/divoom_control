//! Tests for `media_remote`.
//!
//! In a sibling file for the house 500-line cap. Two modules, kept apart
//! because they cover different halves: locating and running the helper, and
//! parsing what it prints.
//!
//! Included with `#[path]`, so the two original `mod` blocks nest one level
//! deeper than they did. The re-export below is what lets their own
//! `use super::*` still reach `media_remote`.

use super::*;

mod parsing {
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
