//! Tests for `verbs` — the CLI's device verbs.
//!
//! Two kinds, and the split matters: argument handling is a pure function and is
//! tested directly, while the wire behaviour is tested through a real socket
//! (the shared `FakeDaemon`), because what can be wrong there is that the
//! request is never sent or the method is wrong — neither of which a mock of
//! `call_tool` would catch.

use super::*;
use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

/// Parse an invocation that IS a verb, insisting on it.
fn verb(argv: &[&str]) -> Result<VerbRequest, String> {
    let owned: Vec<String> = argv.iter().map(|s| (*s).to_string()).collect();
    parse(&owned).unwrap_or_else(|| panic!("expected a verb in {argv:?}"))
}

/// Parse and insist that it is NOT a verb — i.e. the caller should read these
/// arguments as daemon options.
fn not_a_verb(argv: &[&str]) -> bool {
    let owned: Vec<String> = argv.iter().map(|s| (*s).to_string()).collect();
    parse(&owned).is_none()
}

// ── parsing ─────────────────────────────────────────────────────────────

#[test]
fn a_verb_is_recognised_only_by_its_exact_name() {
    // A typo is NOT a verb: it has to stay a daemon-argument error, or
    // `divoomd set-vol 5` would start a daemon and serve the default socket.
    assert!(not_a_verb(&["set-vol", "5"]));
    assert!(not_a_verb(&["--socket", "/tmp/x.sock"]));
    assert!(not_a_verb(&[]));
    // The right NAME with a missing value is a verb with a usage error, not a
    // daemon invocation — the difference matters because one is answered with
    // "expected 1 value" and the other with "unknown argument".
    assert!(
        !not_a_verb(&["set-volume"]),
        "a known name must be treated as a verb even when its value is missing"
    );
    let err = verb(&["set-volume"]).expect_err("no value given");
    assert!(err.contains("expected 1 value"), "{err}");
}

/// Every name in `VERB_NAMES` is one this parser accepts, and nothing else is.
///
/// The advertised list and the `match` used to be two separate things, and a
/// verb in one but not the other would be printed by `--help` and then refused.
/// One test, both directions.
#[test]
fn every_advertised_verb_parses() {
    for name in VERB_NAMES {
        let argv: Vec<&str> = match *name {
            "set-volume" => vec![name, "5"],
            "set-brightness" => vec![name, "50"],
            _ => vec![name, "/etc/hosts"],
        };
        let parsed = verb(&argv);
        assert!(
            parsed.is_ok(),
            "{name} is advertised in --help but rejected: {parsed:?}"
        );
    }
    assert_eq!(
        VERB_NAMES.len(),
        4,
        "a verb was added without a test case above"
    );
}

#[test]
fn the_value_is_parsed_and_bounded() {
    assert_eq!(
        verb(&["set-volume", "5"]).expect("5 is in range").verb,
        Verb::SetVolume { value: 5 }
    );
    assert_eq!(
        verb(&["set-brightness", "100"])
            .expect("100 is the top of the range")
            .verb,
        Verb::SetBrightness { value: 100 }
    );
}

#[test]
fn the_bounds_are_the_ones_the_tool_uses_and_are_checked_at_both_ends() {
    // These bounds are asserted here AND in mcp_tools_tests, deliberately: a
    // shared constant cannot drift, but a change to either surface's limits
    // should break a test rather than quietly widen what reaches the panel.
    for (name, arg, why) in [
        ("set-volume", "16", "above the maximum"),
        ("set-volume", "-1", "below the minimum"),
        ("set-brightness", "101", "above the maximum"),
        ("set-brightness", "-1", "below the minimum"),
    ] {
        let err = verb(&[name, arg]).expect_err(&format!("{name} {arg}: {why}"));
        assert!(err.contains("must be in"), "{name} {arg}: unhelpful: {err}");
        // The message names the range, because the user typed a number and
        // needs to know which numbers are allowed.
        assert!(
            err.contains("0..15") || err.contains("0..100"),
            "{name} {arg}: the range itself must be in the message: {err}"
        );
    }
}

#[test]
fn a_value_that_is_not_a_number_is_an_error_and_never_a_zero() {
    // `set-volume loud` must not mean `set-volume 0`.
    for arg in ["loud", "", "5.5", "0x10"] {
        let err = verb(&["set-volume", arg]).expect_err(&format!("{arg:?} is not a number"));
        assert!(err.contains("is not a number"), "{arg:?}: {err}");
    }
}

#[test]
fn a_missing_or_extra_value_is_an_error() {
    let err = verb(&["set-volume"]).expect_err("no value");
    assert!(err.contains("expected 1 value"), "{err}");
    let err = verb(&["set-volume", "5", "6"]).expect_err("two values");
    assert!(err.contains("expected 1 value"), "{err}");
}

#[test]
fn flags_work_before_and_after_the_value() {
    let forms: [&[&str]; 3] = [
        ["set-volume", "--mac", "AA:BB", "5"].as_slice(),
        ["set-volume", "5", "--mac", "AA:BB"].as_slice(),
        ["set-volume", "5", "--mac=AA:BB"].as_slice(),
    ];
    for argv in forms {
        let parsed = verb(argv).expect("parses");
        assert_eq!(parsed.mac.as_deref(), Some("AA:BB"), "{argv:?}");
        assert_eq!(parsed.verb, Verb::SetVolume { value: 5 });
    }
}

#[test]
fn json_is_remembered() {
    assert!(!verb(&["set-volume", "5"]).expect("ok").json);
    assert!(verb(&["set-volume", "5", "--json"]).expect("ok").json);
}

#[test]
fn a_flag_without_its_value_is_an_error() {
    let err = verb(&["set-volume", "5", "--mac"]).expect_err("--mac eats nothing");
    assert!(err.contains("--mac requires a value"), "{err}");
}

#[test]
fn an_unknown_option_is_an_error_rather_than_being_ignored() {
    // The parser this binary replaced silently ignored what it did not
    // recognise. That is the whole reason it is a pure function with tests.
    let err = verb(&["set-volume", "5", "--loud"]).expect_err("--loud is not a flag");
    assert!(err.contains("unknown option"), "{err}");
}

#[test]
fn a_missing_image_is_refused_before_any_connection() {
    let err = verb(&["push-image", "/nonexistent/divoom/nope.png"]).expect_err("not there");
    assert!(err.contains("file not found"), "{err}");
}

#[test]
fn push_gif_is_the_same_operation_under_another_name() {
    // It was never a special case in Python either: both verbs called
    // show_image(path). Keeping both names keeps scripts working; pretending
    // they differ would be inventing a behaviour nobody implemented.
    let dir = std::env::temp_dir().join(format!("divoom-verbs-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("temp dir");
    let path = dir.join("a.gif");
    std::fs::write(&path, b"GIF89a").expect("write");
    let p = path.to_string_lossy().into_owned();

    let image = verb(&["push-image", &p]).expect("parses").verb;
    let gif = verb(&["push-gif", &p]).expect("parses").verb;
    assert_ne!(image, gif, "the names stay distinct");
    let (Verb::PushImage { path: a }, Verb::PushGif { path: b }) = (image, gif) else {
        panic!("expected the two image verbs")
    };
    assert_eq!(a, b, "but they carry the same path");
    let _ = std::fs::remove_dir_all(&dir);
}

// ── the wire ────────────────────────────────────────────────────────────

#[tokio::test]
async fn set_volume_sends_the_same_call_the_tool_sends() {
    let daemon = FakeDaemon::start(json!({}), None).await;
    let request = verb(&["set-volume", "7", "--mac", "AA:BB"]).expect("parses");
    let outcome = run(&request, &daemon.target)
        .await
        .expect("the call succeeds");

    assert_eq!(outcome.human, "set volume to 7/15");
    assert_eq!(outcome.value["ok"], json!(true));
    let sent = daemon.requests();
    assert_eq!(sent.len(), 1, "one request, not a reconnect storm");
    assert_eq!(sent[0]["command"], json!("device_call"));
    assert_eq!(sent[0]["args"]["method"], json!("music.set_volume"));
    assert_eq!(sent[0]["args"]["args"], json!([7]));
    assert_eq!(
        sent[0]["args"]["mac"],
        json!("AA:BB"),
        "--mac must reach the device"
    );
}

#[tokio::test]
async fn set_brightness_sends_its_own_method() {
    let daemon = FakeDaemon::start(json!({}), None).await;
    let request = verb(&["set-brightness", "40"]).expect("parses");
    run(&request, &daemon.target)
        .await
        .expect("the call succeeds");
    let sent = daemon.requests();
    assert_eq!(sent[0]["args"]["method"], json!("device.set_brightness"));
    assert_eq!(sent[0]["args"]["args"], json!([40]));
    assert!(
        sent[0]["args"].get("mac").is_none(),
        "no --mac means no mac key, not an empty one"
    );
}

#[tokio::test]
async fn an_image_is_pushed_by_path_so_the_daemon_can_size_it() {
    // The whole reason this verb does not go through the MCP `show_image` tool:
    // that tool resizes to a hardcoded 16x16 in the client, while the daemon's
    // handler takes the path and uses the panel's native resolution. A test
    // that only asserted "a request was sent" would not notice the difference;
    // this one asserts the ARGUMENT is the path and nothing else.
    let dir = std::env::temp_dir().join(format!("divoom-verbs-img-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("temp dir");
    let path = dir.join("pic.png");
    std::fs::write(&path, b"\x89PNG").expect("write");
    let p = path.to_string_lossy().into_owned();

    let daemon = FakeDaemon::start(json!({ "result": true }), None).await;
    let request = verb(&["push-image", &p]).expect("parses");
    let outcome = run(&request, &daemon.target)
        .await
        .expect("the call succeeds");

    assert!(outcome.human.contains("pic.png"), "{}", outcome.human);
    assert_eq!(outcome.value["ok"], json!(true));
    let sent = daemon.requests();
    assert_eq!(sent[0]["args"]["method"], json!("display.show_image"));
    assert_eq!(
        sent[0]["args"]["args"],
        json!([p]),
        "the daemon must receive the PATH, not pre-resized RGB"
    );
    let _ = std::fs::remove_dir_all(&dir);
}

#[tokio::test]
async fn a_daemon_that_refuses_is_an_error_not_a_success_message() {
    // The old CLI could print "ok=False" and exit 0-ish; here a refusal is an
    // Err, so the exit code carries the failure. What can be wrong on the wire
    // is that the reply says success:false, and this pins that we read it.
    let daemon = FakeDaemon::replying(
        json!({ "success": false, "error": "no device connected" }),
        None,
    )
    .await;
    let request = verb(&["push-image", "/etc/hosts"]).expect("hosts exists");
    let err = run(&request, &daemon.target)
        .await
        .expect_err("the daemon refused");
    assert!(err.contains("no device connected"), "{err}");
}

#[tokio::test]
async fn an_unreachable_daemon_names_the_socket() {
    let request = verb(&["set-volume", "5"]).expect("parses");
    let err = run(&request, &unreachable())
        .await
        .expect_err("nothing is listening");
    assert!(err.contains("divoom-test.sock"), "unhelpful error: {err}");
}
