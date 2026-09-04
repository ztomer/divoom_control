//! SPP_SCROLL (0x35) wire parity with the APK.
//!
//! Split out of `mock_device_tests.rs` in R73: that file hit the repo's
//! 500-line cap, and scroll is a self-contained subject with its own ground
//! truth (`CmdManager.b3`) worth reading on its own.

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

    /// 0x35 = SPP_SCROLL(53). The APK's only builder is
    /// `CmdManager.b3(mode, speed)`:
    ///
    /// ```text
    /// SPP_SCROLL, { 0, (byte) mode, (byte)(speed & 255), (byte)((speed >> 8) & 255) }
    /// ```
    ///
    /// This pins those four bytes, and pins the two refusals added in R73.
    /// The old handler defaulted `mode`/`speed` to 0 and reported success --
    /// a zero-speed no-op packet indistinguishable from a real call, which
    /// produced two invalid hardware runs before the zeros were spotted.
    #[tokio::test]
    async fn test_mock_set_scroll_matches_the_apk_builder() {
        let d = setup_mock_daemon().await;
        let call = |m: serde_json::Value| {
            let d = &d;
            async move { d.handle(make_request("device_call", Some(m), None)).await }
        };

        // b3(mode=1, speed=300) -> 300 = 0x012C -> LE bytes 2C 01
        assert!(call(json!({"method":"drawing.set_scroll",
                            "kwargs":{"mode":1,"speed":300}}))
        .await["success"]
            .as_bool()
            .unwrap());

        // The legacy name still routes to the same encoder.
        assert!(call(json!({"method":"drawing.pic_scan_ctrl",
                            "kwargs":{"control":0,"mode":2,"speed":20}}))
        .await["success"]
            .as_bool()
            .unwrap());

        // Under-specified: must REFUSE, not send zeros and claim success.
        assert!(
            !call(json!({"method":"drawing.set_scroll","kwargs":{"mode":1}})).await["success"]
                .as_bool()
                .unwrap()
        );
        assert!(
            !call(json!({"method":"drawing.set_scroll","kwargs":{}})).await["success"]
                .as_bool()
                .unwrap()
        );

        // control=1 was invented by the Python lib; b3 is the ONLY builder.
        assert!(!call(json!({"method":"drawing.pic_scan_ctrl",
                             "kwargs":{"control":1,"mode":1,"speed":10}}))
        .await["success"]
            .as_bool()
            .unwrap());

        let device_lock = d.device.lock().await;
        let DeviceTransport::Mock(ref mock) = **device_lock.as_ref().unwrap() else {
            panic!("expected Mock")
        };
        let cmds = mock.sent_commands.lock().unwrap();
        // Exactly the two accepted calls reached the wire.
        assert_eq!(cmds.len(), 2, "refused calls must not send anything");
        assert_eq!(cmds[0], (0x35, vec![0x00, 0x01, 0x2C, 0x01]));
        assert_eq!(cmds[1], (0x35, vec![0x00, 0x02, 0x14, 0x00]));
    }
}
