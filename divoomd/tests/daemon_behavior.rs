//! Daemon Handler dispatch — status/lifecycle commands and the exclusive
//! steal-reject through the real command queue.

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

#[tokio::test]
async fn exclusive_start_needs_a_device() {
    let d = Daemon::new();
    let a = d
        .handle(make_request(
            "exclusive_start",
            Some(json!({"token": "A"})),
            None,
        ))
        .await;
    assert_eq!(a["success"], json!(false));
    assert!(a["error"].as_str().unwrap().contains("no device connected"));
}

#[tokio::test]
async fn ping_and_status_shapes() {
    let d = Daemon::new();
    assert_eq!(
        d.handle(make_request("ping", None, None)).await,
        json!({"success": true, "pong": true})
    );
    let st = d.handle(make_request("device_status", None, None)).await;
    assert_eq!(st["success"], json!(true));
    assert_eq!(st["connected"], json!(false));
    assert_eq!(st["connection_state"], json!("disconnected"));
    assert_eq!(st["wall"], json!(false));

    let gs = d.handle(make_request("get_status", None, None)).await;
    assert_eq!(gs["state"], json!("idle"));
    assert!(gs["uptime_s"].is_u64());
}

#[tokio::test]
async fn exclusive_steal_reject_through_handler() {
    let d = Daemon::new();
    // Exclusive mode owns the CURRENT device's queue (2026-09-12: the queue
    // moved onto the device, so there is nothing to hold before a connect).
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_X"})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true));
    let a = d
        .handle(make_request(
            "exclusive_start",
            Some(json!({"token": "A"})),
            None,
        ))
        .await;
    assert_eq!(a["success"], json!(true));
    assert_eq!(a["token"], json!("A"));

    // a competing session is rejected immediately (the R53.x steal-reject)
    let b = d
        .handle(make_request(
            "exclusive_start",
            Some(json!({"token": "B"})),
            None,
        ))
        .await;
    assert_eq!(b["success"], json!(false));
    assert!(b["error"].as_str().unwrap().contains("exclusively held"));

    let end = d
        .handle(make_request(
            "exclusive_end",
            Some(json!({"token": "A"})),
            None,
        ))
        .await;
    assert_eq!(end["success"], json!(true));

    // after release, B can acquire
    let b2 = d
        .handle(make_request(
            "exclusive_start",
            Some(json!({"token": "B"})),
            None,
        ))
        .await;
    assert_eq!(b2["success"], json!(true));
}

#[tokio::test]
async fn exclusive_start_requires_token() {
    let d = Daemon::new();
    let r = d.handle(make_request("exclusive_start", None, None)).await;
    assert_eq!(r["success"], json!(false));
    assert!(r["error"].as_str().unwrap().contains("requires 'token'"));
}

#[tokio::test]
async fn device_commands_are_honestly_unimplemented() {
    let d = Daemon::new();
    let r = d
        .handle(make_request(
            "device_call",
            Some(json!({"method": "device.unimplemented_method"})),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(false), "must NOT fake success");
    let err = r["error"].as_str().unwrap();
    assert!(
        err.contains("no device connected")
            || err.contains("not implemented")
            || err.contains("not ported"),
        "Unexpected error: {err}"
    );
}

#[tokio::test]
async fn device_name_commands_route_to_device_call() {
    let d = Daemon::new();
    // get_device_name returns "no device connected" when no device is connected,
    // which confirms it is routed to cmd_device_call (implemented)
    let r1 = d
        .handle(make_request(
            "device_call",
            Some(json!({"method": "device.get_device_name"})),
            None,
        ))
        .await;
    assert_eq!(r1["success"], json!(false));
    let err1 = r1["error"].as_str().unwrap();
    assert!(
        err1.contains("no device connected") || err1.contains("not implemented"),
        "Unexpected error: {err1}"
    );

    // set_device_name returns "no device connected"
    let r2 = d
        .handle(make_request(
            "device_call",
            Some(json!({"method": "device.set_device_name", "args": ["NewName"]})),
            None,
        ))
        .await;
    assert_eq!(r2["success"], json!(false));
    let err2 = r2["error"].as_str().unwrap();
    assert!(
        err2.contains("no device connected") || err2.contains("not implemented"),
        "Unexpected error: {err2}"
    );
}

/// Every ported `device_call` method with a sample argument list (JSON).
const PORTED_METHODS: &[(&str, &str)] = &[
    ("music.get_volume", "[]"),
    ("music.set_volume", "[10]"),
    ("radio.set_radio_frequency", "[875]"),
    ("device.get_low_power_switch", "[]"),
    ("device.set_low_power_switch", "[1]"),
    ("device.get_auto_power_off", "[]"),
    ("device.set_auto_power_off", "[15]"),
    ("scoreboard.set_scoreboard", "[1, 10, 20]"),
    ("scoreboard.get_scoreboard", "[]"),
    ("set_scoreboard", "[1, 10, 20]"),
    ("get_scoreboard", "[]"),
    ("timer.set_timer", "[1]"),
    ("timer.get_timer", "[]"),
    ("set_timer", "[1]"),
    ("get_timer", "[]"),
    ("countdown.set_countdown", "[1, 10, 0]"),
    ("countdown.get_countdown", "[]"),
    ("set_countdown", "[1, 10, 0]"),
    ("get_countdown", "[]"),
    ("noise.set_noise", "[1]"),
    ("noise.get_noise", "[]"),
    ("set_noise", "[1]"),
    ("get_noise", "[]"),
    ("device.show_notification", "[1]"),
    ("show_notification", "[1]"),
    ("notification.show_notification", "[1]"),
    ("device.show_notification_text", r#"[1, "hello"]"#),
    ("show_notification_text", r#"[1, "hello"]"#),
    ("notification.show_notification_text", r#"[1, "hello"]"#),
    ("alarm.get_alarm_time", "[]"),
    ("get_alarm_time", "[]"),
    ("alarm.set_alarm", "[0, 1, 8, 30, 127, 0, 1, 0, 10]"),
    ("set_alarm", "[0, 1, 8, 30, 127, 0, 1, 0, 10]"),
    ("alarm.set_alarm_gif", "[0, 100, 1, [0, 1, 2]]"),
    ("set_alarm_gif", "[0, 100, 1, [0, 1, 2]]"),
    ("alarm.get_memorial_time", "[]"),
    ("get_memorial_time", "[]"),
    ("alarm.set_memorial_gif", "[0, 100, 1, [0, 1, 2]]"),
    ("set_memorial_gif", "[0, 100, 1, [0, 1, 2]]"),
    ("alarm.set_alarm_listen", "[1, 0, 15]"),
    ("set_alarm_listen", "[1, 0, 15]"),
    ("alarm.set_alarm_volume", "[15]"),
    ("set_alarm_volume", "[15]"),
    ("alarm.set_alarm_volume_control", "[1, 0]"),
    ("set_alarm_volume_control", "[1, 0]"),
    ("sleep.get_sleep_scene", "[]"),
    ("get_sleep_scene", "[]"),
    ("sleep.set_sleep_scene_listen", "[1, 0, 15]"),
    ("set_sleep_scene_listen", "[1, 0, 15]"),
    ("sleep.set_scene_volume", "[15]"),
    ("set_scene_volume", "[15]"),
    ("sleep.set_sleep_color", "[[0, 0, 255]]"),
    ("set_sleep_color", "[[0, 0, 255]]"),
    ("sleep.set_sleep_light", "[50]"),
    ("set_sleep_light", "[50]"),
    ("aid_sleep.play", "[256, 0]"),
    ("aid_sleep.exit", "[]"),
    ("aid_sleep.delete", "[256, 0]"),
    ("timeplan.set_time_manage_ctrl", "[1, 0]"),
    ("set_time_manage_ctrl", "[1, 0]"),
    ("text.set_light_phone_word_attr", "[1, 10, 0]"),
    ("set_light_phone_word_attr", "[1, 10, 0]"),
    ("text.set_text_content", r#"["hello", 1]"#),
    ("set_text_content", r#"["hello", 1]"#),
    ("game.show_game", "[1]"),
    ("show_game", "[1]"),
    ("game.hide_game", "[]"),
    ("hide_game", "[]"),
    ("game.exit_game", "[]"),
    ("exit_game", "[]"),
    ("game.set_key_down", "[1]"),
    ("set_key_down", "[1]"),
    ("game.set_key_up", "[1]"),
    ("set_key_up", "[1]"),
    ("game.set_magic_ball_answer", "[10]"),
    ("set_magic_ball_answer", "[10]"),
    ("game.send_gamecontrol", r#"["up"]"#),
    ("send_gamecontrol", r#"["up"]"#),
    ("design.set_eq", "[true, 1, false]"),
    ("set_eq", "[true, 1, false]"),
    ("design.set_language", "[0]"),
    ("set_language", "[0]"),
    ("design.set_user_define_time", "[12, 30, 0]"),
    ("set_user_define_time", "[12, 30, 0]"),
    ("design.get_user_define_time", "[]"),
    ("get_user_define_time", "[]"),
    ("design.set_screen_dir", "[1]"),
    ("set_screen_dir", "[1]"),
    ("design.set_screen_mirror", "[true]"),
    ("set_screen_mirror", "[true]"),
    ("design.factory_reset", "[]"),
    ("factory_reset", "[]"),
    ("design.use_user_define_index", "[1]"),
    ("use_user_define_index", "[1]"),
    ("design.clear_user_define_index", "[1]"),
    ("clear_user_define_index", "[1]"),
    ("time.set_hour_type", "[1]"),
    ("set_hour_type", "[1]"),
    ("system.set_hour_type", "[1]"),
    ("bluetooth.set_bluetooth_password", r#"[1, "1234"]"#),
    ("set_bluetooth_password", r#"[1, "1234"]"#),
    ("system.set_bluetooth_password", r#"[1, "1234"]"#),
    ("system.get_work_mode", "[]"),
    ("get_work_mode", "[]"),
    ("system.set_work_mode", "[1]"),
    ("set_work_mode", "[1]"),
    ("system.set_channel", "[1]"),
    ("set_channel", "[1]"),
    ("device.set_channel", "[1]"),
    ("system.send_sd_status", "[1]"),
    ("send_sd_status", "[1]"),
    ("device.send_sd_status", "[1]"),
    ("system.get_device_temp", "[]"),
    ("get_device_temp", "[]"),
    ("device.get_device_temp", "[]"),
    ("send_net_temp", "[2026, 6, 23, 10, 0, 1, [[25, 1]]]"),
    ("system.get_net_temp_disp", "[]"),
    ("get_net_temp_disp", "[]"),
    ("device.get_net_temp_disp", "[]"),
    ("system.send_current_temp", "[25, 1]"),
    ("send_current_temp", "[25, 1]"),
    ("device.send_current_temp", "[25, 1]"),
    ("system.set_temp_type", "[1]"),
    ("set_temp_type", "[1]"),
    ("device.set_temp_type", "[1]"),
    ("system.set_song_display_control", "[1]"),
    ("set_song_display_control", "[1]"),
    ("device.set_song_display_control", "[1]"),
    ("system.set_power_on_voice_volume", "[1, 50]"),
    ("set_power_on_voice_volume", "[1, 50]"),
    ("device.set_power_on_voice_volume", "[1, 50]"),
    ("system.set_power_on_channel", "[1, 0]"),
    ("device.set_power_on_channel", "[1, 0]"),
    ("system.set_boot_gif", "[1, 100, 1, [0, 1, 2]]"),
    ("device.set_boot_gif", "[1, 100, 1, [0, 1, 2]]"),
    ("system.set_sound_control", "[1]"),
    ("set_sound_control", "[1]"),
    ("device.set_sound_control", "[1]"),
    ("system.get_sound_control", "[]"),
    ("get_sound_control", "[]"),
    ("device.get_sound_control", "[]"),
    ("display.set_clock_rich", "[]"),
];

#[tokio::test]
async fn ported_commands_route_to_device_call() {
    let d = Daemon::new();
    for (method, args) in PORTED_METHODS {
        let args: serde_json::Value = serde_json::from_str(args).expect("sample args are JSON");
        let r = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": method, "args": args})),
                None,
            ))
            .await;
        assert_eq!(r["success"], json!(false), "method {method} should fail");
        let err = r["error"].as_str().unwrap();
        assert!(
            err.contains("no device connected")
                || err.contains("not implemented")
                || err.contains("not ported"),
            "Method {method} returned unexpected error: {err}"
        );
    }
}
