//! Scrolling marquee text (R73) — wire parity with the APK's own sequence.
//!
//! Ground truth is `CmdManager`: glyph upload (0x7C) in 5-character packets,
//! then the string (0x86 sub 1), then the rate (0x86 sub 0), then start
//! (0x6E). These tests pin the packet boundaries and the exact header bytes,
//! because every one of them is a place a plausible-looking off-by-one would
//! produce a device that shows nothing and reports success — which is how the
//! 0x35 scroll command went three years mis-documented.

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

    async fn sent(d: &Daemon) -> Vec<(u8, Vec<u8>)> {
        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
            panic!("expected Mock")
        };
        let cmds = mock.sent_commands.lock().unwrap();
        cmds.clone()
    }

    #[tokio::test]
    async fn test_scrolling_text_matches_the_apk_sequence() {
        let d = setup_mock_daemon().await;
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method":"text.show_scrolling_text",
                            "kwargs":{"text":"ABCDEFG","rate":40}})),
                None,
            ))
            .await;
        assert!(res["success"].as_bool().unwrap(), "{res}");
        assert_eq!(res["characters"].as_i64().unwrap(), 7);

        let cmds = sent(&d).await;
        // 7 chars -> two glyph packets (5 + 2), then text, rate, start.
        assert_eq!(cmds.len(), 5, "{cmds:?}");

        // -- packet 1: [total=7, start=0, count=5] + 5 * 34 bytes
        let (id, ref p) = cmds[0];
        assert_eq!(id, 0x7C);
        assert_eq!(&p[0..3], &[7, 0, 5]);
        assert_eq!(p.len(), 3 + 5 * 34);
        // 'A' = U+0041 -> LE code unit 41 00, then 32 glyph bytes
        assert_eq!(&p[3..5], &[0x41, 0x00]);

        // -- packet 2: [total=7, start=5, count=2]
        let (id, ref p) = cmds[1];
        assert_eq!(id, 0x7C);
        assert_eq!(&p[0..3], &[7, 5, 2]);
        assert_eq!(p.len(), 3 + 2 * 34);
        assert_eq!(&p[3..5], &[0x46, 0x00]); // 'F'

        // -- the string: [1, count, UTF-16LE]
        let (id, ref p) = cmds[2];
        assert_eq!(id, 0x86);
        assert_eq!(p[0], 1);
        assert_eq!(p[1], 7);
        assert_eq!(&p[2..6], &[0x41, 0x00, 0x42, 0x00]); // "AB"
        assert_eq!(p.len(), 2 + 7 * 2);

        // -- rate, then start
        assert_eq!(cmds[3], (0x86, vec![0, 40]));
        assert_eq!(cmds[4], (0x6E, vec![1]));
    }

    #[tokio::test]
    async fn test_exactly_five_characters_is_one_packet() {
        // The chunk boundary: 5 must NOT produce an empty trailing packet.
        // The APK's loop runs `length/5 + 1` times, so a naive port sends a
        // zero-length chunk for any exact multiple of 5.
        let d = setup_mock_daemon().await;
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method":"text.show_scrolling_text","kwargs":{"text":"HELLO"}})),
                None,
            ))
            .await;
        assert!(res["success"].as_bool().unwrap(), "{res}");
        let cmds = sent(&d).await;
        let glyph_packets: Vec<_> = cmds.iter().filter(|(id, _)| *id == 0x7C).collect();
        assert_eq!(glyph_packets.len(), 1, "{glyph_packets:?}");
        assert_eq!(&glyph_packets[0].1[0..3], &[5, 0, 5]);
    }

    #[tokio::test]
    async fn test_it_refuses_rather_than_sending_something_meaningless() {
        let d = setup_mock_daemon().await;
        for kwargs in [json!({"text":""}), json!({"text":"   "}), json!({})] {
            let res = d
                .handle(make_request(
                    "device_call",
                    Some(json!({"method":"text.show_scrolling_text","kwargs":kwargs})),
                    None,
                ))
                .await;
            assert!(!res["success"].as_bool().unwrap(), "{res}");
        }
        // Over 255 chars cannot be expressed in the length byte.
        let long = "A".repeat(256);
        let res = d
            .handle(make_request(
                "device_call",
                Some(json!({"method":"text.show_scrolling_text","kwargs":{"text":long}})),
                None,
            ))
            .await;
        assert!(!res["success"].as_bool().unwrap(), "{res}");

        assert!(sent(&d).await.is_empty(), "a refused call sent bytes");
    }
}
