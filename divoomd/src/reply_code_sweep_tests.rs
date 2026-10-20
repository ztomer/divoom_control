//! Every failure a request can provoke carries a `code` (P5.10).
//!
//! P3.2 put a stable `code` on failure replies so clients branch on a class
//! rather than on prose (the Settings card, MCP's `ToolError`, the CLI's
//! `<message> [<code>]`). P5.9 closed the missing-argument refusals; this
//! sweep holds the rest: it drives every command the dispatcher answers, and
//! every `device_call` method, down the failure paths a test can reach
//! without a radio or the network -- no panel, an unknown panel, a panel
//! whose every write fails, nonsense arguments, a wall whose panels refuse --
//! and fails on any reply that is not a success and names no known code.
//!
//! The oracle is written here rather than borrowed from the daemon's own
//! wire check, so a defect in that check cannot hide one here.

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use serde_json::{json, Map, Value};

    use crate::command_args::{ArgType, Required, COMMAND_ARGS};
    use crate::daemon::{Daemon, DeviceTransport};
    use crate::protocol::{make_request, ErrorCode};
    use crate::socket_server::Handler;

    /// Commands the sweep does not send, each with what sending it would
    /// touch. Everything else in `COMMAND_ARGS` is driven; the source scan in
    /// `reply_shape_scan_tests` covers these handlers' replies.
    const NOT_DRIVEN: &[(&str, &str)] = &[
        ("scan", "the Bluetooth radio"),
        ("sync_artwork", "the Divoom cloud"),
        ("get_animated_preview", "the Divoom cloud"),
        ("hot_update", "the Divoom cloud"),
        ("hot_manifest", "the Divoom cloud"),
        ("now_playing", "the host's media services"),
        ("players", "the host's media services"),
        ("weather", "a weather provider"),
        ("set_topology", "the user's saved topology file"),
        ("start_notifications", "the host's notification monitor"),
        ("set_routing", "the user's saved routing file"),
        ("fetch_gallery", "the Divoom cloud"),
        (
            "save_credentials",
            "the user's keychain and the Divoom cloud",
        ),
        ("get_credentials", "the Divoom cloud"),
        ("get_category_file_list", "the Divoom cloud"),
        ("get_dial_types", "the Divoom cloud"),
        ("store_clock_faces", "the Divoom cloud"),
        ("get_dial_list", "the Divoom cloud"),
        ("list_clock_faces", "the Divoom cloud"),
        ("search_weather_city", "the Divoom cloud"),
        ("get_aid_sleep_list", "the Divoom cloud"),
        ("get_my_aid_sleep_list", "the Divoom cloud"),
        ("get_my_playlists", "the Divoom cloud"),
        ("get_playlist_images", "the Divoom cloud"),
        ("get_photo_albums", "the Divoom cloud"),
    ];

    const PANEL: &str = "SWEEP_A";

    /// Why `reply` breaks the contract, or `None` when it keeps it.
    fn uncoded(reply: &Value) -> Option<&'static str> {
        match reply.get("success") {
            Some(Value::Bool(true)) => return None,
            Some(Value::Bool(false)) => {}
            _ => return Some("no boolean 'success'"),
        }
        let Some(code) = reply.get("code").and_then(Value::as_str) else {
            return Some("a failure with no 'code'");
        };
        if !ErrorCode::ALL.iter().any(|c| c.as_str() == code) {
            return Some("a 'code' that is not an ErrorCode");
        }
        if !reply.get("error").is_some_and(Value::is_string) {
            return Some("a failure with no 'error' prose");
        }
        None
    }

    #[derive(Default)]
    struct Findings {
        sent: usize,
        bad: Vec<String>,
    }

    impl Findings {
        async fn ask(&mut self, d: &Daemon, command: &str, args: Value) {
            let reply = d
                .handle(make_request(command, Some(args.clone()), None))
                .await;
            self.sent += 1;
            if let Some(why) = uncoded(&reply) {
                self.bad.push(format!("{command} {args} -> {why}: {reply}"));
            }
        }

        fn assert_clean(mut self, floor: usize) {
            assert!(self.sent >= floor, "sent only {} requests", self.sent);
            self.bad.sort();
            self.bad.dedup();
            assert!(
                self.bad.is_empty(),
                "{} of {} replies break the code contract:\n{}",
                self.bad.len(),
                self.sent,
                self.bad.join("\n")
            );
        }
    }

    fn sample(t: ArgType) -> Value {
        match t {
            ArgType::Str | ArgType::Any => json!("zz"),
            ArgType::Int => json!(-1),
            ArgType::Bool => json!(true),
            ArgType::Object => json!({}),
            ArgType::Array => json!([]),
        }
    }

    /// The command's requirements met with the first key of each, so the
    /// handler gets past the table to its own failure paths.
    fn filled(required: &[Required]) -> Map<String, Value> {
        required
            .iter()
            .filter_map(|req| req.first())
            .map(|(k, t)| ((*k).to_string(), sample(*t)))
            .collect()
    }

    fn with(mut base: Map<String, Value>, key: &str, v: Value) -> Value {
        base.insert(key.to_string(), v);
        Value::Object(base)
    }

    fn variants(command: &str, required: &[Required]) -> Vec<Value> {
        if command == "connect" {
            // Any real mac or address reaches the radio or the network.
            return vec![json!({}), json!({"mock": true, "mac": "SWEEP_B"})];
        }
        let base = filled(required);
        let mut out = vec![
            json!({}),
            Value::Object(base.clone()),
            with(base.clone(), "mac", json!("NOPE")),
            with(base.clone(), "mac", json!(PANEL)),
            with(base, "token", json!("zz")),
        ];
        if command == "render_widget" {
            for params in [
                json!({"image_b64": "%%%"}),
                json!({"image_b64": "aGVsbG8="}),
            ] {
                out.push(json!({"kind": "album_art", "params": params}));
            }
        }
        out
    }

    fn daemon() -> Arc<Daemon> {
        let d = Arc::new(Daemon::new());
        d.initialize_self_weak(Arc::downgrade(&d));
        d
    }

    async fn with_panel(failing: bool) -> Arc<Daemon> {
        let d = daemon();
        let r = d
            .handle(make_request(
                "connect",
                Some(json!({"mock": true, "mac": PANEL})),
                None,
            ))
            .await;
        assert_eq!(r["success"], json!(true), "{r}");
        set_failing(&d, failing).await;
        d
    }

    async fn set_failing(d: &Daemon, failing: bool) {
        let t = d.current_transport().await.expect("the mock panel");
        let DeviceTransport::Mock(m) = &*t else {
            panic!("expected the mock transport")
        };
        m.set_failing(failing);
    }

    /// Link the mock panel again, failing or not.
    ///
    /// A panel whose every write fails LOSES ITS LINK the first time a
    /// command cannot be sent (P2.8: the link is retired and the drop is
    /// reported). A sweep that kept the broken link would go on asking a
    /// panel that is no longer there, and every method after the first would
    /// be answered "not connected" -- the failure paths this sweep exists to
    /// drive would go untested. So the panel is re-linked before each
    /// method, and the sweep still meets every method on a failing device.
    async fn relink(d: &Daemon, failing: bool) {
        let r = d
            .handle(make_request(
                "connect",
                Some(json!({ "mock": true, "mac": PANEL })),
                None,
            ))
            .await;
        assert_eq!(r["success"], json!(true), "{r}");
        set_failing(d, failing).await;
    }

    #[test]
    fn not_driven_names_only_real_commands() {
        let known: Vec<&str> = COMMAND_ARGS.iter().map(|(c, _)| *c).collect();
        let stale: Vec<&str> = NOT_DRIVEN
            .iter()
            .map(|(c, _)| *c)
            .filter(|c| !known.contains(c))
            .collect();
        assert!(stale.is_empty(), "NOT_DRIVEN names no command: {stale:?}");
    }

    #[tokio::test]
    async fn no_command_fails_without_a_code() {
        let mut f = Findings::default();
        for (command, required) in COMMAND_ARGS {
            if NOT_DRIVEN.iter().any(|(c, _)| c == command) {
                continue;
            }
            for args in variants(command, required) {
                // A fresh daemon per request: one command's effect (a
                // disconnect, a shutdown) must not hide another's paths.
                let (bare, linked, failing) =
                    (daemon(), with_panel(false).await, with_panel(true).await);
                f.ask(&bare, command, args.clone()).await;
                f.ask(&linked, command, args.clone()).await;
                f.ask(&failing, command, args).await;
            }
        }
        f.ask(&daemon(), "frobnicate", json!({})).await;
        f.assert_clean(300);
    }

    fn call_variants(method: &str) -> Vec<Value> {
        vec![
            json!({"method": method}),
            json!({"method": method, "args": [-1]}),
            json!({"method": method, "args": [1_000_000, 1_000_000]}),
            json!({"method": method, "args": ["zz"]}),
            json!({"method": method, "kwargs": {"zz": 1}}),
        ]
    }

    #[tokio::test]
    async fn no_device_call_fails_without_a_code() {
        let mut f = Findings::default();
        for failing in [false, true] {
            let d = with_panel(failing).await;
            for method in crate::device_call::routing::all_methods()
                .chain(["no.such_method", "lan.set_brightness"])
            {
                // A failing panel loses its link on the first failed command
                // (P2.8), so it is linked again before each method: every
                // method still meets a device that fails, not a link that is
                // already gone.
                relink(&d, failing).await;
                for args in call_variants(method) {
                    f.ask(&d, "device_call", args).await;
                }
            }
        }
        f.assert_clean(1000);
    }

    #[tokio::test]
    async fn no_wall_call_fails_without_a_code() {
        const WALL: &[&str] = &[
            "show_image",
            "show_light",
            "show_clock",
            "show_effects",
            "show_visualization",
            "set_brightness",
            "set_volume",
            "switch_channel",
            "get_volume",
        ];
        let mut f = Findings::default();
        let bare = daemon();
        for m in WALL {
            f.ask(&bare, "device_call", json!({"method": m, "target": "wall"}))
                .await;
        }
        let d = with_panel(false).await;
        let slots = json!({"slots": {PANEL: {"x": 0, "y": 0, "size": 16}}});
        let r = d
            .handle(make_request("wall_configure", Some(slots), None))
            .await;
        assert_eq!(r["success"], json!(true), "{r}");
        set_failing(&d, true).await;
        for m in WALL {
            for args in [json!([]), json!(["zz"]), json!([1, 2, 3, 4])] {
                let call = json!({"method": m, "target": "wall", "args": args});
                f.ask(&d, "device_call", call).await;
            }
        }
        f.assert_clean(30);
    }

    /// The daemon's own wire check bites: an uncoded failure fails a debug
    /// build at the boundary, so every test that provokes one goes red.
    #[test]
    #[should_panic(expected = "on the wire")]
    fn the_wire_check_refuses_an_uncoded_failure() {
        crate::error_code::check_on_wire(&json!({"success": false, "error": "x"}));
    }

    #[test]
    fn the_wire_check_judges_replies_not_events() {
        use crate::error_code::uncoded_failure;
        assert!(uncoded_failure(&json!({"type": "status", "connected": true})).is_none());
        assert!(uncoded_failure(&json!({"success": true})).is_none());
        let coded = crate::protocol::err_code(ErrorCode::Busy, "x");
        assert!(uncoded_failure(&coded).is_none());
        assert!(uncoded_failure(&json!({"success": false, "code": "busy"})).is_some());
        assert!(
            uncoded_failure(&json!({"success": false, "error": "x", "code": "nope"})).is_some()
        );
        assert!(uncoded_failure(&json!({"success": "yes", "error": "x"})).is_some());
    }
}
