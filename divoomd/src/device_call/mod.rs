mod args;
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::Request;
use serde_json::Value;
use std::time::Duration;

pub struct CallCtx<'a> {
    pub daemon: &'a Daemon,
    pub dev: &'a DeviceTransport,
    pub args: &'a [i64],
    pub raw_args: &'a [Value],
    pub kwargs: Option<&'a serde_json::Map<String, Value>>,
    pub blob_map: &'a std::sync::Mutex<std::collections::HashMap<usize, Vec<u8>>>,
    pub timeout: Duration,
}

pub mod aid_sleep;
pub mod alarm;
pub mod animation;
pub mod basic;
pub mod design;
pub mod drawing;
pub mod game;
mod lan;
pub mod music;
pub mod sleep;
pub mod system;
pub mod text;
pub mod timeplan;
pub mod tools;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};

pub(crate) use args::{pos_bool, pos_i64};

pub async fn handle_device_call(
    _daemon: &Daemon,
    dev: &DeviceTransport,
    req: &Request,
    _timeout: Duration,
) -> Value {
    let method = match req.args.get("method").and_then(|v| v.as_str()) {
        Some(m) => m,
        None => return crate::protocol::err_reply("device_call requires 'method'"),
    };

    // Numeric positional args (for brightness, clock, etc.).
    //
    // WARNING (R67/C7): this list is COMPACTED — `filter_map` drops every
    // non-numeric entry, so `args[i]` is the i-th NUMBER, not the i-th
    // ARGUMENT. For a call like show_light("#00FFCC", 80, true, 2) it is
    // [80, 2], and `args.get(1)` yields the mode, not the brightness. That
    // silently swapped ambient brightness for the mode number on real hardware
    // until a wire trace caught it.
    //
    // Use `pos_i64()` for anything positional. `args` is retained only for
    // handlers whose arguments are all numeric, where the two agree.
    let args: Vec<i64> = req
        .args
        .get("args")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
        .unwrap_or_default();

    // Raw positional args as Values (for string paths in display.show_image)
    let raw_args: Vec<Value> = req
        .args
        .get("args")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    // Blob map: base64-encoded binary data keyed by positional arg index.
    let mut blob_map_raw: std::collections::HashMap<usize, Vec<u8>> =
        std::collections::HashMap::new();
    if let Some(blobs) = req.args.get("blobs").and_then(|v| v.as_object()) {
        for (idx_str, b64val) in blobs {
            let idx: usize = match idx_str.parse() {
                Ok(i) => i,
                Err(_) => {
                    return crate::protocol::err_reply(&format!("blobs: bad index key '{idx_str}'"))
                }
            };
            let b64 = match b64val.as_str() {
                Some(s) => s,
                None => {
                    return crate::protocol::err_reply(&format!("blobs[{idx_str}]: not a string"))
                }
            };
            match B64.decode(b64) {
                Ok(data) => {
                    blob_map_raw.insert(idx, data);
                }
                Err(e) => {
                    return crate::protocol::err_reply(&format!(
                        "blobs[{idx_str}]: base64 error: {e}"
                    ))
                }
            }
        }
    }
    let blob_map = std::sync::Mutex::new(blob_map_raw);

    if method.starts_with("lan.") {
        if let Some(lan_dev) = dev.lan() {
            let kwargs = req.args.get("kwargs").and_then(|v| v.as_object());
            return lan::handle_lan_call(lan_dev, method, &args, kwargs).await;
        } else {
            return crate::protocol::err_reply("device is not connected via LAN");
        }
    }

    // LAN devices are handled above; everything else (BLE / SPP / Mock) routes
    // through the build-agnostic DeviceTransport method layer.
    {
        if !matches!(dev, DeviceTransport::Lan(_)) {
            let kwargs = req.args.get("kwargs").and_then(|v| v.as_object());
            let ctx = CallCtx {
                daemon: _daemon,
                dev,
                args: &args,
                raw_args: &raw_args,
                kwargs,
                blob_map: &blob_map,
                timeout: _timeout,
            };

            match method {
                // basic.rs commands:
                "system.get_device_name"
                | "device.get_device_name"
                | "get_device_name"
                | "system.set_device_name"
                | "device.set_device_name"
                | "set_device_name"
                | "system.get_brightness"
                | "device.get_brightness"
                | "get_brightness"
                | "system.set_brightness"
                | "device.set_brightness"
                | "set_brightness"
                | "device.show_clock"
                | "show_clock"
                | "device.show_image"
                | "show_image"
                | "display.show_image"
                | "display.display_image"
                | "display.set_clock_rich"
                | "animation.stream_animation_8b"
                | "display.show_clock"
                | "display.show_design"
                | "display.get_brightness"
                | "display.set_brightness"
                | "display.show_light"
                | "light.show_light"
                | "show_light"
                | "display.show_effects"
                | "show_effects"
                | "display.show_visualization"
                | "show_visualization"
                | "display.show_scoreboard"
                | "show_scoreboard"
                | "display.set_temperature_channel"
                | "set_temperature_channel"
                | "display.switch_channel"
                | "switch_channel"
                | "hot_update.show_hot_channel"
                | "show_hot_channel"
                | "hot_update.update"
                | "light.get_light_mode"
                | "get_light_mode"
                | "music.set_volume"
                | "set_volume"
                | "music.get_volume"
                | "get_volume"
                | "radio.set_radio_frequency"
                | "set_radio_frequency"
                | "radio.set_radio"
                | "set_radio"
                | "system.set_low_power_switch"
                | "device.set_low_power_switch"
                | "set_low_power_switch"
                | "device.set_low_power"
                | "set_low_power"
                | "system.get_low_power_switch"
                | "device.get_low_power_switch"
                | "get_low_power_switch"
                | "device.get_low_power"
                | "get_low_power"
                | "system.set_auto_power_off"
                | "device.set_auto_power_off"
                | "set_auto_power_off"
                | "sound.set_auto_power_off"
                | "system.get_auto_power_off"
                | "device.get_auto_power_off"
                | "get_auto_power_off"
                | "sound.get_auto_power_off" => basic::handle(method, ctx).await,

                // alarm.rs:
                "alarm.get_alarm_time"
                | "get_alarm_time"
                | "alarm.set_alarm"
                | "set_alarm"
                | "alarm.set_alarm_gif"
                | "set_alarm_gif"
                | "alarm.get_memorial_time"
                | "get_memorial_time"
                | "alarm.set_memorial_time"
                | "set_memorial_time"
                | "alarm.set_memorial_gif"
                | "set_memorial_gif"
                | "alarm.set_alarm_listen"
                | "set_alarm_listen"
                | "alarm.set_alarm_volume"
                | "set_alarm_volume"
                | "alarm.set_alarm_volume_control"
                | "set_alarm_volume_control" => alarm::handle(method, ctx).await,

                // sleep.rs:
                "sleep.show_sleep"
                | "show_sleep"
                | "sleep.get_sleep_scene"
                | "get_sleep_scene"
                | "sleep.set_sleep_scene_listen"
                | "set_sleep_scene_listen"
                | "sleep.set_scene_volume"
                | "set_scene_volume"
                | "sound.set_sleep_color"
                | "sleep.set_sleep_color"
                | "set_sleep_color"
                | "sleep.set_sleep_light"
                | "set_sleep_light"
                | "sleep.set_sleep_scene"
                | "set_sleep_scene" => sleep::handle(method, ctx).await,

                // aid_sleep.rs:
                "aid_sleep.play" | "aid_sleep.exit" | "aid_sleep.delete" => {
                    aid_sleep::handle(method, ctx).await
                }

                // timeplan.rs:
                "timeplan.set_time_manage_info"
                | "set_time_manage_info"
                | "timeplan.set_time_manage_ctrl"
                | "set_time_manage_ctrl" => timeplan::handle(method, ctx).await,

                // tools.rs:
                "scoreboard.set_scoreboard"
                | "set_scoreboard"
                | "scoreboard.get_scoreboard"
                | "get_scoreboard"
                | "timer.set_timer"
                | "set_timer"
                | "timer.get_timer"
                | "get_timer"
                | "countdown.set_countdown"
                | "set_countdown"
                | "countdown.get_countdown"
                | "get_countdown"
                | "noise.set_noise"
                | "set_noise"
                | "noise.get_noise"
                | "get_noise"
                | "device.show_notification"
                | "show_notification"
                | "notification.show_notification"
                | "device.show_notification_text"
                | "show_notification_text"
                | "notification.show_notification_text"
                | "tool.get_tool_info"
                | "get_tool_info"
                | "tool.set_tool_info"
                | "set_tool_info" => tools::handle(method, ctx).await,

                // text.rs:
                "text.set_light_phone_word_attr"
                | "set_light_phone_word_attr"
                | "text.set_text_content"
                | "set_text_content" => text::handle(method, ctx).await,

                // game.rs:
                "game.show_game"
                | "show_game"
                | "game.hide_game"
                | "hide_game"
                | "game.exit_game"
                | "exit_game"
                | "game.set_key_down"
                | "set_key_down"
                | "game.set_key_up"
                | "set_key_up"
                | "game.set_magic_ball_answer"
                | "set_magic_ball_answer"
                | "game.send_gamecontrol"
                | "send_gamecontrol" => game::handle(method, ctx).await,

                // design.rs:
                "design.set_eq"
                | "set_eq"
                | "design.set_language"
                | "set_language"
                | "design.set_user_define_time"
                | "set_user_define_time"
                | "design.get_user_define_time"
                | "get_user_define_time"
                | "design.set_screen_dir"
                | "set_screen_dir"
                | "design.set_screen_mirror"
                | "set_screen_mirror"
                | "design.factory_reset"
                | "factory_reset"
                | "design.use_user_define_index"
                | "use_user_define_index"
                | "design.clear_user_define_index"
                | "clear_user_define_index" => design::handle(method, ctx).await,

                // system.rs:
                "system.set_date_time"
                | "set_date_time"
                | "sync_time"
                | "time.set_date_time"
                | "time.set_hour_type"
                | "set_hour_type"
                | "system.set_hour_type"
                | "bluetooth.set_bluetooth_password"
                | "set_bluetooth_password"
                | "system.set_bluetooth_password"
                | "device.get_work_mode"
                | "system.get_work_mode"
                | "get_work_mode"
                | "device.set_work_mode"
                | "system.set_work_mode"
                | "set_work_mode"
                | "system.set_channel"
                | "set_channel"
                | "device.set_channel"
                | "control.set_light_mode"
                | "control.set_hot"
                | "set_hot"
                | "control.set_keyboard"
                | "set_keyboard"
                | "weather.set"
                | "weather.set_temperature"
                | "weather.set_weather"
                | "system.send_sd_status"
                | "send_sd_status"
                | "device.send_sd_status"
                | "system.get_device_temp"
                | "get_device_temp"
                | "device.get_device_temp"
                | "system.send_net_temp"
                | "send_net_temp"
                | "device.send_net_temp"
                | "system.send_net_temp_disp"
                | "send_net_temp_disp"
                | "device.send_net_temp_disp"
                | "system.get_net_temp_disp"
                | "get_net_temp_disp"
                | "device.get_net_temp_disp"
                | "system.send_current_temp"
                | "send_current_temp"
                | "device.send_current_temp"
                | "system.set_temp_type"
                | "set_temp_type"
                | "device.set_temp_type"
                | "sound.set_song_display_control"
                | "system.set_song_display_control"
                | "set_song_display_control"
                | "device.set_song_display_control"
                | "sound.set_power_on_voice_volume"
                | "system.set_power_on_voice_volume"
                | "set_power_on_voice_volume"
                | "device.set_power_on_voice_volume"
                | "system.set_power_on_channel"
                | "device.set_power_on_channel"
                | "system.set_boot_gif"
                | "device.set_boot_gif"
                | "sound.set_sound_control"
                | "system.set_sound_control"
                | "set_sound_control"
                | "device.set_sound_control"
                | "sound.get_sound_control"
                | "system.get_sound_control"
                | "get_sound_control"
                | "device.get_sound_control" => system::handle(method, ctx).await,

                // drawing.rs (drawing-pad / sand-paint / movie / scan):
                "drawing.set_light_pic"
                | "set_light_pic"
                | "drawing.drawing_pad_exit"
                | "drawing_pad_exit"
                | "drawing.drawing_mul_encode_gif_play"
                | "drawing_mul_encode_gif_play"
                | "drawing.drawing_ctrl_movie_play"
                | "drawing_ctrl_movie_play"
                | "drawing.drawing_mul_pad_enter"
                | "drawing_mul_pad_enter"
                | "drawing.drawing_pad_ctrl"
                | "drawing_pad_ctrl"
                | "drawing.drawing_mul_pad_ctrl"
                | "drawing_mul_pad_ctrl"
                | "drawing.drawing_big_pad_ctrl"
                | "drawing_big_pad_ctrl"
                | "drawing.drawing_mul_encode_single_pic"
                | "drawing_mul_encode_single_pic"
                | "drawing.drawing_mul_encode_pic"
                | "drawing_mul_encode_pic"
                | "drawing.drawing_encode_movie_play"
                | "drawing_encode_movie_play"
                | "drawing.drawing_mul_encode_movie_play"
                | "drawing_mul_encode_movie_play"
                | "drawing.sand_paint_ctrl"
                | "sand_paint_ctrl"
                | "drawing.pic_scan_ctrl"
                | "pic_scan_ctrl" => drawing::handle(method, ctx).await,

                // music.rs (SD-card music control):
                "music.app_need_get_music_list"
                | "app_need_get_music_list"
                | "music.send_sd_list_over"
                | "send_sd_list_over"
                | "music.set_play_status"
                | "set_play_status"
                | "music.set_sd_last_next"
                | "set_sd_last_next"
                | "music.set_sd_music_play_mode"
                | "set_sd_music_play_mode"
                | "music.set_sd_music_position"
                | "set_sd_music_position"
                | "music.set_sd_play_music_id"
                | "set_sd_play_music_id"
                | "music.set_sd_music_info"
                | "set_sd_music_info"
                | "music.get_play_status"
                | "get_play_status"
                | "music.get_sd_music_list_total_num"
                | "get_sd_music_list_total_num"
                | "music.get_sd_music_info"
                | "get_sd_music_info"
                | "music.get_sd_play_name"
                | "get_sd_play_name"
                | "music.get_sd_music_list"
                | "get_sd_music_list" => music::handle(method, ctx).await,

                // animation.rs (gif/user-define upload primitives):
                "animation.set_gif_speed"
                | "set_gif_speed"
                | "animation.set_light_phone_gif"
                | "set_light_phone_gif"
                | "animation.set_rhythm_gif"
                | "set_rhythm_gif"
                | "animation.app_send_eq_gif"
                | "app_send_eq_gif"
                | "animation.app_new_send_gif_cmd"
                | "app_new_send_gif_cmd"
                | "animation.set_user_gif"
                | "set_user_gif"
                | "animation.app_new_user_define"
                | "app_new_user_define"
                | "animation.app_big64_user_define"
                | "app_big64_user_define"
                | "animation.modify_user_gif_items"
                | "modify_user_gif_items"
                | "animation.app_get_user_define_info"
                | "app_get_user_define_info" => animation::handle(method, ctx).await,

                m => crate::protocol::err_reply(&format!("device_call method not ported yet: {m}")),
            }
        } else {
            crate::protocol::err_reply("method only supported on a BLE/SPP device")
        }
    }
}
