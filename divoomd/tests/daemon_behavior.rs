//! Daemon Handler dispatch — status/lifecycle commands and the exclusive
//! steal-reject through the real command queue.

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

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
        "Unexpected error: {}",
        err
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
        "Unexpected error: {}",
        err1
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
        "Unexpected error: {}",
        err2
    );
}

#[tokio::test]
async fn ported_commands_route_to_device_call() {
    let d = Daemon::new();
    let methods = vec![
        ("music.get_volume", json!([])),
        ("music.set_volume", json!([10])),
        ("radio.set_radio_frequency", json!([875])),
        ("device.get_low_power_switch", json!([])),
        ("device.set_low_power_switch", json!([1])),
        ("device.get_auto_power_off", json!([])),
        ("device.set_auto_power_off", json!([15])),
        ("scoreboard.set_scoreboard", json!([1, 10, 20])),
        ("scoreboard.get_scoreboard", json!([])),
        ("set_scoreboard", json!([1, 10, 20])),
        ("get_scoreboard", json!([])),
        ("timer.set_timer", json!([1])),
        ("timer.get_timer", json!([])),
        ("set_timer", json!([1])),
        ("get_timer", json!([])),
        ("countdown.set_countdown", json!([1, 10, 0])),
        ("countdown.get_countdown", json!([])),
        ("set_countdown", json!([1, 10, 0])),
        ("get_countdown", json!([])),
        ("noise.set_noise", json!([1])),
        ("noise.get_noise", json!([])),
        ("set_noise", json!([1])),
        ("get_noise", json!([])),
        ("device.show_notification", json!([1])),
        ("show_notification", json!([1])),
        ("notification.show_notification", json!([1])),
        ("device.show_notification_text", json!([1, "hello"])),
        ("show_notification_text", json!([1, "hello"])),
        ("notification.show_notification_text", json!([1, "hello"])),
        ("alarm.get_alarm_time", json!([])),
        ("get_alarm_time", json!([])),
        ("alarm.set_alarm", json!([0, 1, 8, 30, 127, 0, 1, 0, 10])),
        ("set_alarm", json!([0, 1, 8, 30, 127, 0, 1, 0, 10])),
        ("alarm.set_alarm_gif", json!([0, 100, 1, [0, 1, 2]])),
        ("set_alarm_gif", json!([0, 100, 1, [0, 1, 2]])),
        ("alarm.get_memorial_time", json!([])),
        ("get_memorial_time", json!([])),
        (
            "alarm.set_memorial_time",
            json!([0, 1, 1, 1, 12, 0, 1, "Memorial"]),
        ),
        (
            "set_memorial_time",
            json!([0, 1, 1, 1, 12, 0, 1, "Memorial"]),
        ),
        ("alarm.set_memorial_gif", json!([0, 100, 1, [0, 1, 2]])),
        ("set_memorial_gif", json!([0, 100, 1, [0, 1, 2]])),
        ("alarm.set_alarm_listen", json!([1, 0, 15])),
        ("set_alarm_listen", json!([1, 0, 15])),
        ("alarm.set_alarm_volume", json!([15])),
        ("set_alarm_volume", json!([15])),
        ("alarm.set_alarm_volume_control", json!([1, 0])),
        ("set_alarm_volume_control", json!([1, 0])),
        (
            "sleep.show_sleep",
            json!([60, 0, 1, 875, 10, [255, 255, 255], 100]),
        ),
        (
            "show_sleep",
            json!([60, 0, 1, 875, 10, [255, 255, 255], 100]),
        ),
        ("sleep.get_sleep_scene", json!([])),
        ("get_sleep_scene", json!([])),
        ("sleep.set_sleep_scene_listen", json!([1, 0, 15])),
        ("set_sleep_scene_listen", json!([1, 0, 15])),
        ("sleep.set_scene_volume", json!([15])),
        ("set_scene_volume", json!([15])),
        ("sleep.set_sleep_color", json!([[0, 0, 255]])),
        ("set_sleep_color", json!([[0, 0, 255]])),
        ("sleep.set_sleep_light", json!([50])),
        ("set_sleep_light", json!([50])),
        (
            "sleep.set_sleep_scene",
            json!([0, 1, [0, 0], 10, [255, 255, 255], 50]),
        ),
        (
            "set_sleep_scene",
            json!([0, 1, [0, 0], 10, [255, 255, 255], 50]),
        ),
        ("aid_sleep.play", json!([256, 0])),
        ("aid_sleep.exit", json!([])),
        ("aid_sleep.delete", json!([256, 0])),
        (
            "timeplan.set_time_manage_info",
            json!([1, 8, 0, 127, 0, 1, 875, 15, 1]),
        ),
        (
            "set_time_manage_info",
            json!([1, 8, 0, 127, 0, 1, 875, 15, 1]),
        ),
        ("timeplan.set_time_manage_ctrl", json!([1, 0])),
        ("set_time_manage_ctrl", json!([1, 0])),
        ("text.set_light_phone_word_attr", json!([1, 10, 0])),
        ("set_light_phone_word_attr", json!([1, 10, 0])),
        ("text.set_text_content", json!(["hello", 1])),
        ("set_text_content", json!(["hello", 1])),
        ("game.show_game", json!([1])),
        ("show_game", json!([1])),
        ("game.hide_game", json!([])),
        ("hide_game", json!([])),
        ("game.exit_game", json!([])),
        ("exit_game", json!([])),
        ("game.set_key_down", json!([1])),
        ("set_key_down", json!([1])),
        ("game.set_key_up", json!([1])),
        ("set_key_up", json!([1])),
        ("game.set_magic_ball_answer", json!([10])),
        ("set_magic_ball_answer", json!([10])),
        ("game.send_gamecontrol", json!(["up"])),
        ("send_gamecontrol", json!(["up"])),
        ("design.set_eq", json!([true, 1, false])),
        ("set_eq", json!([true, 1, false])),
        ("design.set_language", json!([0])),
        ("set_language", json!([0])),
        ("design.set_user_define_time", json!([12, 30, 0])),
        ("set_user_define_time", json!([12, 30, 0])),
        ("design.get_user_define_time", json!([])),
        ("get_user_define_time", json!([])),
        ("design.set_screen_dir", json!([1])),
        ("set_screen_dir", json!([1])),
        ("design.set_screen_mirror", json!([true])),
        ("set_screen_mirror", json!([true])),
        ("design.factory_reset", json!([])),
        ("factory_reset", json!([])),
        ("design.use_user_define_index", json!([1])),
        ("use_user_define_index", json!([1])),
        ("design.clear_user_define_index", json!([1])),
        ("clear_user_define_index", json!([1])),
        ("time.set_hour_type", json!([1])),
        ("set_hour_type", json!([1])),
        ("system.set_hour_type", json!([1])),
        ("bluetooth.set_bluetooth_password", json!([1, "1234"])),
        ("set_bluetooth_password", json!([1, "1234"])),
        ("system.set_bluetooth_password", json!([1, "1234"])),
        ("system.get_work_mode", json!([])),
        ("get_work_mode", json!([])),
        ("system.set_work_mode", json!([1])),
        ("set_work_mode", json!([1])),
        ("system.set_channel", json!([1])),
        ("set_channel", json!([1])),
        ("device.set_channel", json!([1])),
        ("system.send_sd_status", json!([1])),
        ("send_sd_status", json!([1])),
        ("device.send_sd_status", json!([1])),
        ("system.get_device_temp", json!([])),
        ("get_device_temp", json!([])),
        ("device.get_device_temp", json!([])),
        (
            "system.send_net_temp",
            json!([2026, 6, 23, 10, 0, 1, [[25, 1]]]),
        ),
        ("send_net_temp", json!([2026, 6, 23, 10, 0, 1, [[25, 1]]])),
        (
            "device.send_net_temp",
            json!([2026, 6, 23, 10, 0, 1, [[25, 1]]]),
        ),
        (
            "system.send_net_temp_disp",
            json!([[true, false, false, false, false], 30]),
        ),
        (
            "send_net_temp_disp",
            json!([[true, false, false, false, false], 30]),
        ),
        (
            "device.send_net_temp_disp",
            json!([[true, false, false, false, false], 30]),
        ),
        ("system.get_net_temp_disp", json!([])),
        ("get_net_temp_disp", json!([])),
        ("device.get_net_temp_disp", json!([])),
        ("system.send_current_temp", json!([25, 1])),
        ("send_current_temp", json!([25, 1])),
        ("device.send_current_temp", json!([25, 1])),
        ("system.set_temp_type", json!([1])),
        ("set_temp_type", json!([1])),
        ("device.set_temp_type", json!([1])),
        ("system.set_song_display_control", json!([1])),
        ("set_song_display_control", json!([1])),
        ("device.set_song_display_control", json!([1])),
        ("system.set_power_on_voice_volume", json!([1, 50])),
        ("set_power_on_voice_volume", json!([1, 50])),
        ("device.set_power_on_voice_volume", json!([1, 50])),
        ("system.set_power_on_channel", json!([1, 0])),
        ("device.set_power_on_channel", json!([1, 0])),
        ("system.set_boot_gif", json!([1, 100, 1, [0, 1, 2]])),
        ("device.set_boot_gif", json!([1, 100, 1, [0, 1, 2]])),
        ("system.set_sound_control", json!([1])),
        ("set_sound_control", json!([1])),
        ("device.set_sound_control", json!([1])),
        ("system.get_sound_control", json!([])),
        ("get_sound_control", json!([])),
        ("device.get_sound_control", json!([])),
        ("display.set_clock_rich", json!([])),
    ];

    for (method, args) in methods {
        let r = d
            .handle(make_request(
                "device_call",
                Some(json!({"method": method, "args": args})),
                None,
            ))
            .await;
        assert_eq!(r["success"], json!(false), "method {} should fail", method);
        let err = r["error"].as_str().unwrap();
        assert!(
            err.contains("no device connected")
                || err.contains("not implemented")
                || err.contains("not ported"),
            "Method {} returned unexpected error: {}",
            method,
            err
        );
    }
}
