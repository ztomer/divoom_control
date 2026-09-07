//! Mock-device tests, second half: channels, animation and music payloads.
//!
//! Split from `mock_device_tests` for the house 500-line cap. The
//! `setup_mock_daemon` helper and the note on holding the recorded-commands
//! lock both live in that file; these tests reach the helper through it.

#[cfg(test)]
mod tests {
    use super::super::mock_device_tests::tests::setup_mock_daemon;
    use crate::daemon::DeviceTransport;
    use crate::protocol::make_request;
    use crate::socket_server::Handler;
    use serde_json::json;

    /// Display channel methods (parity with Python Display.*): each is a 0x45
    /// "set light mode" with a specific payload. Asserts exact wire bytes.
    #[tokio::test]
    async fn test_mock_display_channels() {
        let d = setup_mock_daemon().await;
        let call = |m: serde_json::Value| {
            let d = &d;
            async move { d.handle(make_request("device_call", Some(m), None)).await }
        };
        // show_effects(2) -> 0x45 [0x03, 3, 0×8]
        assert!(
            call(json!({"method":"display.show_effects","args":[2]})).await["success"]
                .as_bool()
                .unwrap()
        );
        // show_visualization(1) -> 0x45 [0x04, 1, 0×8]
        assert!(
            call(json!({"method":"display.show_visualization","args":[1]})).await["success"]
                .as_bool()
                .unwrap()
        );
        // show_scoreboard -> 0x45 [0x06, 0×9]
        assert!(
            call(json!({"method":"display.show_scoreboard"})).await["success"]
                .as_bool()
                .unwrap()
        );
        // switch_channel("design") -> 0x45 [0x05, 0×9]
        assert!(
            call(json!({"method":"display.switch_channel","args":["design"]})).await["success"]
                .as_bool()
                .unwrap()
        );

        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
            drop(device_lock);
            panic!("expected Mock")
        };
        let cmds = mock.sent_commands.lock().unwrap();
        // R73: was 5 — the set_temperature_channel frame that used to sit at
        // index 3 sent `[0x01, temp_type, R, G, B, 0x00]`, which the device
        // parses as the LIGHTING channel (0x01) with temp_type eaten as red.
        // Disproven on hardware; command removed. See docs/CHANNEL_ARCHITECTURE.md.
        assert_eq!(cmds.len(), 4);
        assert_eq!(cmds[0], (0x45, vec![0x03, 0x03, 0, 0, 0, 0, 0, 0, 0, 0]));
        assert_eq!(cmds[1], (0x45, vec![0x04, 0x01, 0, 0, 0, 0, 0, 0, 0, 0]));
        assert_eq!(cmds[2], (0x45, vec![0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0]));
        assert_eq!(cmds[3], (0x45, vec![0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0]));
    }

    /// Animation upload primitives — verify exact wire bytes incl. LE/BE orders
    /// (parity with `divoom_lib/display/animation`*.py).
    #[tokio::test]
    async fn test_mock_animation_payloads() {
        let d = setup_mock_daemon().await;
        let call = |m: serde_json::Value| {
            let d = &d;
            async move { d.handle(make_request("device_call", Some(m), None)).await }
        };
        assert!(
            call(json!({"method":"animation.set_gif_speed","args":[100]})).await["success"]
                .as_bool()
                .unwrap()
        );
        assert!(call(json!({"method":"animation.set_rhythm_gif","kwargs":{"pos":1,"total_length":512,"gif_id":2,"data":[170,187]}})).await["success"].as_bool().unwrap());
        assert!(call(json!({"method":"animation.app_new_send_gif_cmd","kwargs":{"control_word":0,"file_size":300}})).await["success"].as_bool().unwrap());
        assert!(call(json!({"method":"animation.app_big64_user_define","kwargs":{"control_word":0,"file_size":10,"index":2,"file_id":16_909_060}})).await["success"].as_bool().unwrap());

        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
            drop(device_lock);
            panic!()
        };
        let cmds = mock.sent_commands.lock().unwrap();
        assert_eq!(cmds[0], (0x16, vec![0x64, 0x00])); // speed 100 LE16
        assert_eq!(cmds[1], (0xb7, vec![1, 0x00, 0x02, 2, 0xAA, 0xBB])); // pos, len 512 LE16, id, data
        assert_eq!(cmds[2], (0x8b, vec![0, 0x2C, 0x01, 0x00, 0x00])); // cw0, file_size 300 LE32
        assert_eq!(
            cmds[3],
            (0x8d, vec![0, 0x0A, 0, 0, 0, 2, 0x01, 0x02, 0x03, 0x04])
        ); // file_size LE32, idx, file_id BE32
    }

    /// SD-card music setters — wire-byte parity with `divoom_lib/media/music.py`.
    #[tokio::test]
    async fn test_mock_music_sd_payloads() {
        let d = setup_mock_daemon().await;
        let call = |m: serde_json::Value| {
            let d = &d;
            async move { d.handle(make_request("device_call", Some(m), None)).await }
        };
        assert!(
            call(json!({"method":"music.set_play_status","args":[1]})).await["success"]
                .as_bool()
                .unwrap()
        );
        assert!(
            call(json!({"method":"music.set_sd_music_position","args":[60]})).await["success"]
                .as_bool()
                .unwrap()
        );
        assert!(call(json!({"method":"music.set_sd_music_info","kwargs":{"current_time":60,"music_id":1,"volume":10,"status":1,"play_mode":2}})).await["success"].as_bool().unwrap());
        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
            drop(device_lock);
            panic!()
        };
        let cmds = mock.sent_commands.lock().unwrap();
        assert_eq!(cmds[0], (0x0a, vec![1]));
        assert_eq!(cmds[1], (0xb8, vec![60, 0])); // position 60 LE16
        assert_eq!(cmds[2], (0xb5, vec![60, 0, 1, 0, 10, 1, 2])); // cur LE16, id LE16, vol, status, mode
    }

    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
    #[tokio::test]
    async fn test_mock_music_set_volume() {
        let d = setup_mock_daemon().await;

        let call_res = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "music.set_volume",
                    "args": [12]
                })),
                None,
            ))
            .await;

        assert!(call_res["success"].as_bool().unwrap_or(false));

        let device_lock = d.device.lock().await;
        if let Some(ref transport_arc) = &*device_lock {
            if let DeviceTransport::Mock(ref mock) = **transport_arc {
                let cmds = mock.sent_commands.lock().unwrap();
                assert_eq!(cmds.len(), 1);
                let (cmd_id, payload) = &cmds[0];
                assert_eq!(*cmd_id, 0x08);
                assert_eq!(*payload, vec![12]);
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

    /// R67/C7: positional args must be read by their TRUE index.
    ///
    /// `show_light(color, brightness, power, lightning_type)` is forwarded
    /// positionally by `DaemonDeviceProxy`. The handler used to index the
    /// COMPACTED numeric list, which drops the colour string and the bool — so
    /// for ("#00FFCC", 80, true, 2) it was [80, 2] and index 1 gave the MODE.
    /// The ambient brightness slider therefore transmitted the mode number, and
    /// mode 0 meant brightness 0. Only a wire trace on real hardware exposed it.
    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
    #[tokio::test]
    async fn test_mock_show_light_reads_brightness_not_the_mode() {
        for (mode, want_type) in [(0u8, 0u8), (2, 2), (4, 4)] {
            let d = setup_mock_daemon().await;
            let call_res = d
                .handle(make_request(
                    "device_call",
                    Some(json!({
                        "method": "display.show_light",
                        // A STRING first — this is what shifts the numeric list.
                        "args": ["#00FFCC", 80, true, mode],
                    })),
                    None,
                ))
                .await;
            assert!(call_res["success"].as_bool().unwrap_or(false));

            let device_lock = d.device.lock().await;
            let transport_arc = device_lock.as_ref().expect("connected device");
            let DeviceTransport::Mock(ref mock) = **transport_arc else {
                panic!("Expected Mock transport");
            };
            let cmds = mock.sent_commands.lock().unwrap();
            let (cmd_id, payload) = &cmds[0];
            assert_eq!(*cmd_id, 0x45);
            assert_eq!(
                *payload,
                vec![0x01, 0x00, 0xFF, 0xCC, 80, want_type, 0x01, 0x00, 0x00, 0x00],
                "mode {mode}: brightness must be 80 (not the mode), type must be {want_type}"
            );
        }
    }

    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
    #[tokio::test]
    async fn test_mock_show_light_honours_power_off_positionally() {
        let d = setup_mock_daemon().await;
        let call_res = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "display.show_light",
                    "args": ["#FF0000", 55, false, 1],
                })),
                None,
            ))
            .await;
        assert!(call_res["success"].as_bool().unwrap_or(false));

        let device_lock = d.device.lock().await;
        let transport_arc = device_lock.as_ref().expect("connected device");
        let DeviceTransport::Mock(ref mock) = **transport_arc else {
            panic!("Expected Mock transport");
        };
        let cmds = mock.sent_commands.lock().unwrap();
        let (_, payload) = &cmds[0];
        assert_eq!(payload[4], 55, "brightness");
        assert_eq!(payload[5], 1, "lighting type");
        assert_eq!(payload[6], 0, "power off must survive the positional read");
    }
}
