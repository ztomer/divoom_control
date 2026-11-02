//! D.FX1: no channel write leaves the panel dark unless dark was asked for.
//!
//! A one-byte `set_channel 1` (`0x45 01`) turned a Ditoo dark and left its
//! brightness at 0. The lighting channel's nine bytes after the selector ARE
//! its configuration -- `[1, R, G, B, brightness, type, power, 0, 0, 0]`, the
//! APK's `CmdManager.y2` -- so a short or zero-filled packet asks for black at
//! brightness 0 with the light off, and the firmware does exactly that (the
//! P9.7 trace read brightness and on/off as 0 after it). It is the 2026-09-07
//! blank-clock class again: a channel that carries configuration was sent bare.
//!
//! These walk EVERY route a channel is selected by -- the numeric
//! `set_channel` (and its aliases) and the named `switch_channel` -- over every
//! channel, so a route or a channel added later is covered by the same rule.
#[cfg(test)]
mod tests {
    use crate::daemon::{Daemon, DeviceTransport};
    use crate::packets::Channel;
    use crate::protocol::make_request;
    use crate::socket_server::Handler;
    use serde_json::{json, Value};

    async fn sent(method: &str, args: Value) -> Result<(u8, Vec<u8>), Value> {
        sent_over(method, args, None).await
    }

    /// The 0x45 the call sent, with the panel's 0x46 answer staged as `light`.
    async fn sent_over(
        method: &str,
        args: Value,
        light: Option<Vec<u8>>,
    ) -> Result<(u8, Vec<u8>), Value> {
        let d = Daemon::new();
        let conn = d
            .handle(make_request("connect", Some(json!({"mock": true})), None))
            .await;
        assert!(conn["success"].as_bool().unwrap_or(false));
        if let Some(light) = light {
            let guard = d.current_transport().await;
            let transport = guard.as_ref().expect("connected device");
            let DeviceTransport::Mock(ref mock) = **transport else {
                panic!("expected mock transport")
            };
            mock.simulated_responses.lock().unwrap().insert(0x46, light);
        }
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": method, "args": args})),
                None,
            ))
            .await;
        if !res["success"].as_bool().unwrap_or(false) {
            return Err(res);
        }
        let guard = d.current_transport().await;
        let transport = guard.as_ref().expect("connected device");
        let DeviceTransport::Mock(ref mock) = **transport else {
            panic!("expected mock transport")
        };
        let select = mock
            .sent_commands
            .lock()
            .unwrap()
            .iter()
            .rfind(|(id, _)| *id == 0x45)
            .cloned()
            .expect("a 0x45 channel select");
        Ok(select)
    }

    /// The rule every channel packet must satisfy, whatever route built it.
    fn assert_selects_without_darkening(route: &str, id: u8, payload: &[u8]) {
        assert_eq!(payload.len(), 10, "{route}: a short 0x45 is {payload:?}");
        assert_eq!(payload[0], id, "{route}: selector byte");
        if id == Channel::Lighting as u8 {
            assert!(
                payload[4] > 0,
                "{route}: the light channel was sent brightness 0: {payload:?}"
            );
            assert_eq!(
                payload[6], 1,
                "{route}: the light was sent OFF: {payload:?}"
            );
            assert_ne!(
                &payload[1..4],
                &[0, 0, 0],
                "{route}: black light: {payload:?}"
            );
        }
        if id == Channel::Clock as u8 {
            assert_eq!(payload[3], 1, "{route}: inactive clock face: {payload:?}");
        }
    }

    #[tokio::test]
    async fn every_numeric_channel_selects_a_whole_packet() {
        for method in [
            "set_channel",
            "system.set_channel",
            "device.set_channel",
            "control.set_light_mode",
        ] {
            for id in 0u8..=6 {
                let (cmd, payload) = sent(method, json!([id]))
                    .await
                    .unwrap_or_else(|e| panic!("{method}({id}) failed: {e}"));
                assert_eq!(cmd, 0x45, "{method}({id})");
                assert_selects_without_darkening(&format!("{method}({id})"), id, &payload);
            }
        }
    }

    #[tokio::test]
    async fn every_named_channel_selects_a_whole_packet() {
        for (name, id) in [
            ("clock", Channel::Clock),
            ("ambient", Channel::Lighting),
            ("lighting", Channel::Lighting),
            ("light", Channel::Lighting),
            ("cloud", Channel::Cloud),
            ("hot", Channel::Cloud),
            ("vj", Channel::Vj),
            ("visualizer", Channel::Visualization),
            ("design", Channel::Design),
            ("scoreboard", Channel::Scoreboard),
        ] {
            let (cmd, payload) = sent("display.switch_channel", json!([name]))
                .await
                .unwrap_or_else(|e| panic!("switch_channel({name}) failed: {e}"));
            assert_eq!(cmd, 0x45, "switch_channel({name})");
            assert_selects_without_darkening(
                &format!("switch_channel({name})"),
                id as u8,
                &payload,
            );
        }
    }

    #[tokio::test]
    async fn a_channel_no_panel_has_is_refused_not_sent() {
        let err = sent("set_channel", json!([7]))
            .await
            .expect_err("channel 7 does not exist");
        assert_eq!(err["code"], "bad_request", "{err}");
    }

    /// D.FX5: selecting the light channel never changes a brightness the
    /// caller did not ask to change. Live: brightness 50, `set_channel 1`,
    /// and `get_brightness` read 100 -- the select carried a fixed 100.
    #[tokio::test]
    async fn the_light_select_keeps_the_panels_brightness_and_colour() {
        // 0x46 answer: [mode, temp, vj, R, G, B, brightness, type, power, ...]
        let light = vec![0, 0, 0, 0x10, 0x20, 0x30, 50, 0, 1, 0, 80, 0];
        for (method, args) in [
            ("set_channel", json!([1])),
            ("control.set_light_mode", json!([1])),
            ("display.switch_channel", json!(["light"])),
        ] {
            let (cmd, payload) = sent_over(method, args.clone(), Some(light.clone()))
                .await
                .unwrap_or_else(|e| panic!("{method}({args}) failed: {e}"));
            assert_eq!(cmd, 0x45, "{method}");
            assert_eq!(payload[4], 50, "{method}: brightness changed: {payload:?}");
            assert_eq!(&payload[1..4], &[0x10, 0x20, 0x30], "{method}: colour");
            assert_eq!(payload[6], 1, "{method}: the light was sent OFF");
        }
    }
}
