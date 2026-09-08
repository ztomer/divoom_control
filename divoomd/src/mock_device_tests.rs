//! Mock-device command tests.
//!
//! # On holding the recorded-commands lock
//!
//! These tests read `mock.sent_commands` through the guard and assert against
//! it directly. Taking the lock ONCE per test is what makes the assertions a
//! single consistent observation, and a second `lock()` while the first guard
//! is alive deadlocks the non-reentrant mutex. The
//! `significant_drop_tightening` expectations point here rather than repeating
//! that seven times.
#[cfg(test)]
pub mod tests {
    use crate::daemon::{Daemon, DeviceTransport};
    use crate::protocol::make_request;
    use crate::socket_server::Handler;
    use serde_json::json;

    /// A daemon wired to the mock transport, connected and ready.
    ///
    /// # Panics
    ///
    /// If the mock connect does not succeed, which in a test means the harness
    /// itself is broken rather than the code under test.
    pub async fn setup_mock_daemon() -> Daemon {
        let d = Daemon::new();
        let conn_res = d
            .handle(make_request("connect", Some(json!({"mock": true})), None))
            .await;
        assert!(conn_res["success"].as_bool().unwrap_or(false));
        d
    }

    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
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

    /// R12/hardware, 2026-09-07: the weather job set data for a face it never
    /// selected.
    ///
    /// `0x5F` updates the temperature and icon ON the weather face; it does not
    /// bring that face forward. With the panel left in the Design channel by the
    /// album-art job, the daemon answered `{"success": true}` and the operator
    /// kept seeing album art. Every other live widget pushes frames into the
    /// channel it selects and is self-sufficient; weather is the only one whose
    /// output is owned by a DIFFERENT channel.
    ///
    /// So the ORDER is the property: the channel switch must precede the data.
    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
    #[tokio::test]
    async fn test_mock_weather_selects_the_clock_face_before_sending_data() {
        use crate::packets::WeatherType;
        use crate::weather::WeatherInfo;

        let d = setup_mock_daemon().await;
        let transport = d.device.lock().await.clone().expect("a mock device");
        crate::live_jobs::push_weather(
            &transport,
            WeatherInfo { temperature_c: 21, weather: WeatherType::Clear },
            true,
        )
        .await;

        let device_lock = d.device.lock().await;
        if let Some(ref transport_arc) = &*device_lock {
            if let DeviceTransport::Mock(ref mock) = **transport_arc {
                let cmds = mock.sent_commands.lock().unwrap();
                let switch = cmds
                    .iter()
                    .position(|(id, p)| *id == 0x45 && p.first() == Some(&0x00))
                    .expect("a 0x45 switch to the Clock channel (0x00)");
                let data = cmds
                    .iter()
                    .position(|(id, _)| *id == 0x5F)
                    .expect("the 0x5F weather packet");
                assert!(
                    switch < data,
                    "the channel switch must come BEFORE the weather data, \
                     or the data lands on a face the device is not showing"
                );
            } else {
                panic!("Expected Mock transport");
            }
        } else {
            panic!("Expected connected device");
        }
    }

    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
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

    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
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

    #[expect(clippy::significant_drop_tightening, reason = "see the module note")]
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
    /// steal), foreign-token `device_calls` are denied while held, and the slot frees
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
}
