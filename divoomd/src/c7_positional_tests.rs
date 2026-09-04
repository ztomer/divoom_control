//! R67/C7 regression tests: positional arguments after a non-numeric parameter.
//!
//! Split out of `mock_device_tests.rs` in R67 when that file crossed the house
//! 500-line cap. The gate that prevents new instances is
//! `tools/check_positional_args.py`; these pin the five that were real.

/// R67/C7 audit: positional arguments after a NON-NUMERIC parameter.
///
/// `device_call` builds its numeric `args` list with `filter_map(as_i64)`,
/// which COMPACTS — strings, bools and lists vanish. Any handler that read
/// `args[N]` while a non-numeric parameter sat at or before N was reading a
/// neighbouring argument's value with complete confidence.
///
/// An audit of all 64 positional-reading handlers found 9 candidates, of
/// which 5 were real. Each is pinned below with a call that passes the
/// non-numeric parameter POSITIONALLY — the shape that breaks. Keyword
/// callers always worked, which is why these survived.
#[cfg(test)]
mod tests {
    use crate::daemon::{Daemon, DeviceTransport};
    use crate::protocol::make_request;
    use crate::socket_server::Handler;
    use serde_json::json;

    async fn setup_mock_daemon() -> Daemon {
        let d = Daemon::new();
        let conn = d
            .handle(make_request("connect", Some(json!({"mock": true})), None))
            .await;
        assert!(conn["success"].as_bool().unwrap_or(false));
        d
    }

    async fn sent(method: &str, args: serde_json::Value) -> (u8, Vec<u8>) {
        let d = setup_mock_daemon().await;
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": method, "args": args})),
                None,
            ))
            .await;
        assert!(
            res["success"].as_bool().unwrap_or(false),
            "{method} failed: {res}"
        );
        let guard = d.device.lock().await;
        let transport = guard.as_ref().expect("connected device");
        let DeviceTransport::Mock(ref mock) = **transport else {
            panic!("expected mock transport")
        };
        let cmds = mock.sent_commands.lock().unwrap();
        let (id, payload) = &cmds[0];
        (*id, payload.clone())
    }

    #[tokio::test]
    async fn set_hot_honours_a_positional_bool() {
        // `true` is not an i64, so the numeric list was EMPTY and a
        // positional set_hot(True) sent FALSE.
        let (id, payload) = sent("control.set_hot", json!([true])).await;
        assert_eq!(id, 0x26);
        assert_eq!(payload, vec![1], "set_hot(True) must send 1, not 0");

        let (_, off) = sent("control.set_hot", json!([false])).await;
        assert_eq!(off, vec![0]);
    }

    #[tokio::test]
    async fn set_eq_reads_mode_not_the_next_number() {
        // set_eq(dynamic: bool, mode: int, ...) — the bool is dropped, so
        // args[1] was the SECOND number rather than `mode`.
        // Wire: [0x1e, dynamic, mode, stream]
        let (id, payload) = sent("design.set_eq", json!([false, 7, false])).await;
        assert_eq!(id, 0xbd);
        assert_eq!(payload[0], 0x1e);
        assert_eq!(payload[2], 7, "mode must be 7, not the next number");
        assert_eq!(payload[1], 0, "dynamic came from the bool at position 0");
    }

    #[tokio::test]
    async fn send_net_temp_disp_keeps_a_positional_time() {
        // (display_modes: list, time_minutes: int) — the list is dropped, so
        // args[1] was past the end and time_minutes was always lost.
        let (id, payload) = sent("system.send_net_temp_disp", json!([[1, 2], 45])).await;
        assert_eq!(id, 0x5e);
        assert!(
            payload.contains(&45u8),
            "time_minutes 45 must reach the wire, got {payload:?}"
        );
    }

    #[tokio::test]
    async fn show_sleep_maps_every_positional_to_its_own_field() {
        // (value, sleeptime, sleepmode, volume, color, brightness,
        //  frequency, on) — `value` and `color` are non-numeric, so every
        // index after them was wrong, and `color` itself was read from 5.
        let (id, payload) = sent(
            "sleep.show_sleep",
            json!([null, 30, 2, 9, [10, 20, 30], 50, 1077, 1]),
        )
        .await;
        assert_eq!(id, 0x40);
        assert!(
            payload.contains(&30u8),
            "sleeptime 30 must reach the wire: {payload:?}"
        );
        assert!(
            payload.windows(3).any(|w| w == [10, 20, 30]),
            "the colour at position 4 must reach the wire: {payload:?}"
        );
    }

    #[tokio::test]
    async fn set_sleep_scene_reads_volume_and_light_past_the_lists() {
        // (mode, on, fm_freq: list, volume, color: list, light) — two lists
        // are dropped, so `volume` read the 4th NUMBER (which is `light`)
        // and `light` fell off the end entirely.
        let (id, payload) = sent(
            "sleep.set_sleep_scene",
            json!([1, 1, [0, 0], 12, [1, 2, 3], 5]),
        )
        .await;
        assert_eq!(id, 0x41);
        assert_eq!(payload[4], 12, "volume is at true position 3");
        assert_eq!(payload[8], 5, "light is at true position 5");
    }
}

/// R67: `switch_channel` used to hand-write five 0x45 byte arrays, one of which
/// was a full clock packet spelled out by hand. These pin the bytes so the
/// conversion to the shared builders is provably behaviour-preserving.
#[cfg(test)]
mod switch_channel_tests {
    use crate::daemon::{Daemon, DeviceTransport};
    use crate::protocol::make_request;
    use crate::socket_server::Handler;
    use serde_json::json;

    async fn sent(channel: &str) -> (u8, Vec<u8>) {
        let d = Daemon::new();
        let conn = d
            .handle(make_request("connect", Some(json!({"mock": true})), None))
            .await;
        assert!(conn["success"].as_bool().unwrap_or(false));
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": "display.switch_channel", "args": [channel]})),
                None,
            ))
            .await;
        assert!(
            res["success"].as_bool().unwrap_or(false),
            "{channel}: {res}"
        );
        let guard = d.device.lock().await;
        let transport = guard.as_ref().expect("connected device");
        let DeviceTransport::Mock(ref mock) = **transport else {
            panic!("expected mock transport")
        };
        let cmds = mock.sent_commands.lock().unwrap();
        let (id, payload) = &cmds[0];
        (*id, payload.clone())
    }

    #[tokio::test]
    async fn every_channel_keeps_its_exact_bytes() {
        // The pre-refactor arrays, byte for byte.
        for (channel, want) in [
            ("clock", vec![0x00, 1, 0, 1, 0, 0, 0, 0xFF, 0xFF, 0xFF]),
            ("visualizer", vec![0x04, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            ("vj", vec![0x03, 1, 0, 0, 0, 0, 0, 0, 0, 0]),
            ("design", vec![0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            ("scoreboard", vec![0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        ] {
            let (id, payload) = sent(channel).await;
            assert_eq!(id, 0x45, "{channel} must go out as 0x45");
            assert_eq!(payload, want, "{channel} payload changed");
        }
    }

    #[tokio::test]
    async fn an_unknown_channel_is_refused_not_guessed() {
        let d = Daemon::new();
        d.handle(make_request("connect", Some(json!({"mock": true})), None))
            .await;
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": "display.switch_channel", "args": ["nonsense"]})),
                None,
            ))
            .await;
        assert!(!res["success"].as_bool().unwrap_or(false));
        assert!(res["error"].as_str().unwrap_or("").contains("nonsense"));
    }
}
