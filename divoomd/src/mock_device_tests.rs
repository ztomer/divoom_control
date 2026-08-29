#[cfg(test)]
mod tests {
    use crate::daemon::{Daemon, DeviceTransport};
    use crate::protocol::make_request;
    use crate::socket_server::Handler;
    use serde_json::json;

    async fn setup_mock_daemon() -> Daemon {
        let d = Daemon::new();
        let conn_res = d
            .handle(make_request("connect", Some(json!({"mock": true})), None))
            .await;
        assert!(conn_res["success"].as_bool().unwrap_or(false));
        d
    }

    #[tokio::test]
    async fn test_mock_display_set_clock_rich() {
        let d = setup_mock_daemon().await;

        let call_res = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "display.set_clock_rich",
                    "kwargs": {
                        "style": 3,
                        "twentyfour": true,
                        "humidity": true,
                        "weather": false,
                        "date": true,
                        "color": "#ff00ff"
                    }
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
                assert_eq!(*cmd_id, 0x45);
                // Expected APK C2 bytes: [0x00, 0x01, 0x03, 0x01, 0x01, 0x00, 0x01, 0xFF, 0x00, 0xFF]
                assert_eq!(
                    *payload,
                    vec![0x00, 0x01, 0x03, 0x01, 0x01, 0x00, 0x01, 0xFF, 0x00, 0xFF]
                );
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

    #[tokio::test]
    async fn test_mock_display_show_clock() {
        let d = setup_mock_daemon().await;

        let call_res = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "display.show_clock",
                    // R67/C1: this used to pass weather/temp/calendar. Those
                    // were the WRONG names — the canonical overlay fields (the
                    // Python builder, from the APK's C2()) are
                    // humidity/weather/date, and this arm wrote the three
                    // kwargs it did accept straight into bytes 4/5/6. So the
                    // call said "weather + temp" and the bytes below actually
                    // mean "humidity + weather".
                    //
                    // The pinned BYTES were right (validated against
                    // hass-divoom) and are unchanged; only the names that
                    // produce them are corrected. A golden test that encodes
                    // the wrong field names is part of the defect, not a
                    // constraint on fixing it.
                    "kwargs": {
                        "clock": 4,
                        "twentyfour": false,
                        "humidity": true,
                        "weather": true,
                        "date": false,
                        "color": "#00ff00"
                    }
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
                assert_eq!(*cmd_id, 0x45);
                // Expected hass-divoom show_clock bytes: [0x00, 0x00, 0x04, 0x01, 0x01, 0x01, 0x00, 0x00, 0xFF, 0x00]
                assert_eq!(
                    *payload,
                    vec![0x00, 0x00, 0x04, 0x01, 0x01, 0x01, 0x00, 0x00, 0xFF, 0x00]
                );
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

    #[tokio::test]
    async fn test_mock_device_set_brightness() {
        let d = setup_mock_daemon().await;

        let call_res = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "device.set_brightness",
                    "args": [75]
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
                assert_eq!(*cmd_id, 0x74);
                assert_eq!(*payload, vec![75]);
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

    #[tokio::test]
    async fn test_mock_set_date_time() {
        let d = setup_mock_daemon().await;
        // Ported from divoom_lib/system/date_time.py: cmd 0x18, payload
        // [year%100, year//100, month, day, hour, minute, second, 0].
        let call_res = d.handle(make_request("device_call", Some(json!({
            "method": "set_date_time",
            "kwargs": { "year": 2026, "month": 6, "day": 29, "hour": 19, "minute": 53, "second": 7 }
        })), None)).await;

        assert!(call_res["success"].as_bool().unwrap_or(false));
        let device_lock = d.device.lock().await;
        if let Some(ref transport_arc) = &*device_lock {
            if let DeviceTransport::Mock(ref mock) = **transport_arc {
                let cmds = mock.sent_commands.lock().unwrap();
                assert_eq!(cmds.len(), 1);
                let (cmd_id, payload) = &cmds[0];
                assert_eq!(*cmd_id, 0x18);
                assert_eq!(*payload, vec![26, 20, 6, 29, 19, 53, 7, 0]);
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

    /// Phase 4 Tier A: exclusive-mode gating end-to-end through the real daemon
    /// dispatch, hardware-free (mock transport). Mirrors the Python R53 steal-reject
    /// teeth tests: a second session's acquire is rejected IMMEDIATELY (no hang, no
    /// steal), foreign-token device_calls are denied while held, and the slot frees
    /// on release.
    #[tokio::test]
    async fn test_mock_exclusive_mode_gating() {
        let d = setup_mock_daemon().await;

        // Session A acquires the exclusive slot.
        let a = d
            .handle(make_request(
                "exclusive_start",
                Some(json!({"token": "sessA"})),
                None,
            ))
            .await;
        assert!(
            a["success"].as_bool().unwrap_or(false),
            "A should acquire the slot"
        );

        // Session B's acquire is rejected immediately (steal-reject, no hang).
        let b = d
            .handle(make_request(
                "exclusive_start",
                Some(json!({"token": "sessB"})),
                None,
            ))
            .await;
        assert!(
            !b["success"].as_bool().unwrap_or(true),
            "B's steal must be rejected"
        );

        // A device_call carrying B's token is denied while A holds the slot.
        let denied = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "device.set_brightness", "args": [50], "token": "sessB"
                })),
                None,
            ))
            .await;
        assert!(
            !denied["success"].as_bool().unwrap_or(true),
            "B's call must be denied while A holds"
        );

        // A's own device_call routes through to the device.
        let ok = d
            .handle(make_request(
                "device_call",
                Some(json!({
                    "method": "device.set_brightness", "args": [50], "token": "sessA"
                })),
                None,
            ))
            .await;
        assert!(
            ok["success"].as_bool().unwrap_or(false),
            "A's own call should pass"
        );

        // A releases; B can now acquire.
        let end = d
            .handle(make_request(
                "exclusive_end",
                Some(json!({"token": "sessA"})),
                None,
            ))
            .await;
        assert!(
            end["success"].as_bool().unwrap_or(false),
            "A should release"
        );
        let b2 = d
            .handle(make_request(
                "exclusive_start",
                Some(json!({"token": "sessB"})),
                None,
            ))
            .await;
        assert!(
            b2["success"].as_bool().unwrap_or(false),
            "B should acquire after release"
        );

        // Exactly one device_call (A's) reached the device, with the right wire bytes.
        let device_lock = d.device.lock().await;
        if let Some(ref transport_arc) = &*device_lock {
            if let DeviceTransport::Mock(ref mock) = **transport_arc {
                let cmds = mock.sent_commands.lock().unwrap();
                assert_eq!(cmds.len(), 1, "only A's call should reach the device");
                assert_eq!(cmds[0].0, 0x74);
                assert_eq!(cmds[0].1, vec![50]);
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

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
        // set_temperature_channel(celsius=false, #ff0000) -> 0x45 [0x01,1,ff,00,00,00]
        assert!(call(json!({"method":"display.set_temperature_channel","kwargs":{"celsius":false,"color":"#ff0000"}})).await["success"].as_bool().unwrap());
        // switch_channel("design") -> 0x45 [0x05, 0×9]
        assert!(
            call(json!({"method":"display.switch_channel","args":["design"]})).await["success"]
                .as_bool()
                .unwrap()
        );

        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
            panic!("expected Mock")
        };
        let cmds = mock.sent_commands.lock().unwrap();
        assert_eq!(cmds.len(), 5);
        assert_eq!(cmds[0], (0x45, vec![0x03, 0x03, 0, 0, 0, 0, 0, 0, 0, 0]));
        assert_eq!(cmds[1], (0x45, vec![0x04, 0x01, 0, 0, 0, 0, 0, 0, 0, 0]));
        assert_eq!(cmds[2], (0x45, vec![0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0]));
        assert_eq!(cmds[3], (0x45, vec![0x01, 0x01, 0xFF, 0x00, 0x00, 0x00]));
        assert_eq!(cmds[4], (0x45, vec![0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0]));
    }

    /// Animation upload primitives — verify exact wire bytes incl. LE/BE orders
    /// (parity with divoom_lib/display/animation*.py).
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
        assert!(call(json!({"method":"animation.app_big64_user_define","kwargs":{"control_word":0,"file_size":10,"index":2,"file_id":16909060}})).await["success"].as_bool().unwrap());

        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
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

    /// SD-card music setters — wire-byte parity with divoom_lib/media/music.py.
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
            panic!()
        };
        let cmds = mock.sent_commands.lock().unwrap();
        assert_eq!(cmds[0], (0x0a, vec![1]));
        assert_eq!(cmds[1], (0xb8, vec![60, 0])); // position 60 LE16
        assert_eq!(cmds[2], (0xb5, vec![60, 0, 1, 0, 10, 1, 2])); // cur LE16, id LE16, vol, status, mode
    }

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
    /// positionally by DaemonDeviceProxy. The handler used to index the
    /// COMPACTED numeric list, which drops the colour string and the bool — so
    /// for ("#00FFCC", 80, true, 2) it was [80, 2] and index 1 gave the MODE.
    /// The ambient brightness slider therefore transmitted the mode number, and
    /// mode 0 meant brightness 0. Only a wire trace on real hardware exposed it.
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
