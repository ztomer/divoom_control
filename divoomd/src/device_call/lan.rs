//! LAN-transport device_call dispatch (`lan.*` methods) — split out of
//! `mod.rs` to keep it under the 500-line house limit. Routed here from
//! `handle_device_call` when `method.starts_with("lan.")` and the device is
//! LAN-connected.

use serde_json::{json, Value};

pub(super) fn get_arg_i64(
    args: &[i64],
    kw: Option<&serde_json::Map<String, Value>>,
    idx: usize,
    name: &str,
    default: i64,
) -> i64 {
    if idx < args.len() {
        return args[idx];
    }
    if let Some(map) = kw {
        if let Some(val) = map.get(name) {
            if let Some(n) = val.as_i64() {
                return n;
            }
        }
    }
    default
}

/// PhotoList-style array args only make sense as a kwarg (positional `args`
/// is pre-filtered to i64s and silently drops arrays) — see photo album
/// commands below.
fn get_arg_i64_array(kw: Option<&serde_json::Map<String, Value>>, name: &str) -> Vec<i64> {
    kw.and_then(|m| m.get(name))
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_i64()).collect())
        .unwrap_or_default()
}

fn get_arg_str(kw: Option<&serde_json::Map<String, Value>>, name: &str, default: &str) -> String {
    kw.and_then(|m| m.get(name))
        .and_then(|v| v.as_str())
        .unwrap_or(default)
        .to_string()
}

pub(super) async fn handle_lan_call(
    lan: &crate::lan::LanTransport,
    method: &str,
    args: &[i64],
    kw: Option<&serde_json::Map<String, Value>>,
) -> Value {
    let res = match method {
        "lan.set_channel" => {
            let index = get_arg_i64(args, kw, 0, "SelectIndex", 0);
            lan.post("Channel/SetIndex", Some(json!({ "SelectIndex": index })))
                .await
        }
        "lan.get_channel" => lan.post("Channel/GetIndex", None).await,
        "lan.set_brightness" => {
            let val = get_arg_i64(args, kw, 0, "Brightness", 100);
            lan.post("Channel/SetBrightness", Some(json!({ "Brightness": val })))
                .await
        }
        "lan.set_clock" => {
            let clock_id = get_arg_i64(args, kw, 0, "ClockId", 0);
            lan.post(
                "Channel/SetClockSelectId",
                Some(json!({ "ClockId": clock_id })),
            )
            .await
        }
        "lan.send_playlist" => {
            let play_id = get_arg_i64(args, kw, 0, "PlayId", 0);
            lan.post("Playlist/SendDevice", Some(json!({ "PlayId": play_id })))
                .await
        }
        "lan.on_off_screen" => {
            let on_off = get_arg_i64(args, kw, 0, "OnOff", 1);
            lan.post("Channel/OnOffScreen", Some(json!({ "OnOff": on_off })))
                .await
        }
        "lan.set_ambient_light" => {
            let brightness = get_arg_i64(args, kw, 0, "Brightness", 100);
            let color = if let Some(c) = kw.and_then(|m| m.get("Color")).and_then(|v| v.as_str()) {
                c.to_string()
            } else {
                let r = get_arg_i64(args, kw, 1, "r", 0) as u8;
                let g = get_arg_i64(args, kw, 2, "g", 0) as u8;
                let b = get_arg_i64(args, kw, 3, "b", 0) as u8;
                format!("#{:02X}{:02X}{:02X}", r, g, b)
            };
            let power = get_arg_i64(args, kw, 4, "Power", 1);
            lan.post(
                "Channel/SetAmbientLight",
                Some(json!({
                    "Brightness": brightness,
                    "Color": color,
                    "Power": power,
                })),
            )
            .await
        }
        "lan.set_rgb_info" => {
            let mode = get_arg_i64(args, kw, 0, "RgbMode", 1);
            let speed = get_arg_i64(args, kw, 1, "RgbSpeed", 50);
            let color = if let Some(c) = kw.and_then(|m| m.get("RgbColor")).and_then(|v| v.as_str())
            {
                c.to_string()
            } else {
                let r = get_arg_i64(args, kw, 2, "r", 0) as u8;
                let g = get_arg_i64(args, kw, 3, "g", 0) as u8;
                let b = get_arg_i64(args, kw, 4, "b", 0) as u8;
                format!("#{:02X}{:02X}{:02X}", r, g, b)
            };
            lan.post(
                "Channel/SetRGBInfo",
                Some(json!({
                    "RgbMode": mode,
                    "RgbSpeed": speed,
                    "RgbColor": color,
                })),
            )
            .await
        }
        "lan.set_timer" => {
            let minute = get_arg_i64(args, kw, 0, "Minute", 0);
            let second = get_arg_i64(args, kw, 1, "Second", 0);
            let status = get_arg_i64(args, kw, 2, "Status", 0);
            lan.post(
                "Tools/SetTimer",
                Some(json!({
                    "Minute": minute,
                    "Second": second,
                    "Status": status,
                })),
            )
            .await
        }
        "lan.set_scoreboard" => {
            let blue = get_arg_i64(args, kw, 0, "BlueScore", 0);
            let red = get_arg_i64(args, kw, 1, "RedScore", 0);
            lan.post(
                "Tools/SetScoreBoard",
                Some(json!({
                    "BlueScore": blue,
                    "RedScore": red,
                })),
            )
            .await
        }
        "lan.set_stopwatch" => {
            let status = get_arg_i64(args, kw, 0, "Status", 0);
            lan.post("Tools/SetStopWatch", Some(json!({ "Status": status })))
                .await
        }
        "lan.set_noise_status" => {
            let status = get_arg_i64(args, kw, 0, "NoiseStatus", 0);
            lan.post(
                "Tools/SetNoiseStatus",
                Some(json!({ "NoiseStatus": status })),
            )
            .await
        }

        // Photo album management (docs/cloud_api/photo_discover.md) — all five
        // are in HttpCommand.DeviceAndServerCmd (LAN-routed on WiFi).
        "lan.play_album" => {
            let album_id = get_arg_i64(args, kw, 0, "AlbumId", 0);
            lan.post("Photo/PlayAlbum", Some(json!({ "AlbumId": album_id })))
                .await
        }
        "lan.set_album_cover" => {
            let clock_id = get_arg_i64(args, kw, 0, "ClockId", 0);
            let file_id = get_arg_str(kw, "FileId", "");
            let photo_id = get_arg_i64(args, kw, 1, "PhotoId", 0);
            lan.post(
                "Photo/SetAlbumCover",
                Some(json!({
                    "ClockId": clock_id, "FileId": file_id, "PhotoId": photo_id,
                })),
            )
            .await
        }
        "lan.delete_photo" => {
            let clock_id = get_arg_i64(args, kw, 0, "ClockId", 0);
            let photo_list = get_arg_i64_array(kw, "PhotoList");
            lan.post(
                "Photo/DeletePhoto",
                Some(json!({
                    "ClockId": clock_id, "PhotoList": photo_list,
                })),
            )
            .await
        }
        "lan.remove_photo_from_album" => {
            let clock_id = get_arg_i64(args, kw, 0, "ClockId", 0);
            let photo_list = get_arg_i64_array(kw, "PhotoList");
            lan.post(
                "Photo/RemovePhotoFromAlbum",
                Some(json!({
                    "ClockId": clock_id, "PhotoList": photo_list,
                })),
            )
            .await
        }
        "lan.move_photo_to_album" => {
            let to_clock_id = get_arg_i64(args, kw, 0, "ToClockId", 0);
            let photo_list = get_arg_i64_array(kw, "PhotoList");
            lan.post(
                "Photo/DevicePhotoToAlbum",
                Some(json!({
                    "ToClockId": to_clock_id, "PhotoList": photo_list,
                })),
            )
            .await
        }
        // Photo/GetPhotoList: in HttpCommand.ForceDeviceHttp (ALWAYS local,
        // never cloud, unlike the DeviceAndServerCmd group above).
        "lan.get_photo_list" => {
            let clock_id = get_arg_i64(args, kw, 0, "ClockId", 0);
            let parent_clock_id = get_arg_i64(args, kw, 1, "ParentClockId", 0);
            let parent_item_id = get_arg_i64(args, kw, 2, "ParentItemId", 0);
            let limit = get_arg_i64(args, kw, 3, "limit", 30).max(1);
            let page = get_arg_i64(args, kw, 4, "page", 1).max(1);
            let start = (page - 1) * limit + 1;
            let end = page * limit;
            lan.post(
                "Photo/GetPhotoList",
                Some(json!({
                    "ClockId": clock_id, "ParentClockId": parent_clock_id,
                    "ParentItemId": parent_item_id, "StartNum": start, "EndNum": end,
                })),
            )
            .await
        }

        // LAN-getter completeness pass: read-back counterparts of Set
        // commands already implemented above (or over BLE in tools.rs) —
        // same feature, reachable over LAN when the device is on WiFi.
        // Bare GET requests, no body, mirroring lan.get_channel.
        "lan.get_eq_position" => lan.post("Channel/GetEqPosition", None).await,
        "lan.get_rgb_info" => lan.post("Channel/GetRGBInfo", None).await,
        "lan.get_ambient_light" => lan.post("Channel/GetAmbientLight", None).await,
        "lan.get_on_off_screen" => lan.post("Channel/GetOnOffScreen", None).await,
        "lan.get_noise_status" => lan.post("Tools/GetNoiseStatus", None).await,
        "lan.get_timer" => lan.post("Tools/GetTimer", None).await,
        "lan.get_scoreboard" => lan.post("Tools/GetScoreBoard", None).await,
        "lan.get_stopwatch" => lan.post("Tools/GetStopWatch", None).await,

        // Channel extras (docs/cloud_api/channel_b.md) — niche multi-panel
        // (5-LCD "Times Gate") and night-preview features. All in
        // HttpCommand.DeviceAndServerCmd. No live caller of Set5LcdChannelType
        // et al was found beyond WifiChannel* fragments — implemented at the
        // plumbing layer only, no GUI hook (these need real 5-LCD hardware
        // to verify, which this project doesn't have reason to own).
        "lan.set_5lcd_channel_type" => {
            let channel_type = get_arg_i64(args, kw, 0, "ChannelType", 0);
            let lcd_independence = get_arg_i64(args, kw, 1, "LcdIndependence", 0);
            lan.post(
                "Channel/Set5LcdChannelType",
                Some(json!({
                    "ChannelType": channel_type, "LcdIndependence": lcd_independence,
                })),
            )
            .await
        }
        "lan.set_5lcd_whole_clock_id" => {
            let clock_id = get_arg_i64(args, kw, 0, "ClockId", 0);
            lan.post(
                "Channel/Set5LcdWholeClockId",
                Some(json!({ "ClockId": clock_id })),
            )
            .await
        }
        "lan.set_produce_time" => {
            let produce_time = get_arg_i64(args, kw, 0, "ProduceTime", 0);
            lan.post(
                "Channel/SetProduceTime",
                Some(json!({ "ProduceTime": produce_time })),
            )
            .await
        }
        "lan.set_night_preview" => {
            let brightness = get_arg_i64(args, kw, 0, "Brightness", 0);
            lan.post(
                "Channel/SetNightPreview",
                Some(json!({ "Brightness": brightness })),
            )
            .await
        }
        "lan.exit_night_preview" => lan.post("Channel/ExitNightPreview", None).await,

        // Voice/SendText (docs/cloud_api/playlist_voice_timeplan.md) — a
        // text-to-speech-style greeting/banner push, in DeviceAndServerCmd.
        // NOT GUI-wired: this project's existing push_text feature already
        // learned the hard way (R32 §D) that a superficially-similar
        // "set light phone word" command can fail to render on Pixoo-class
        // matrices despite ACKing cleanly — Voice/SendText needs the same
        // real-hardware confirmation before it's trusted, which push_text's
        // known-working bitmap-render path already gets around entirely.
        "lan.send_voice_text" => {
            let text = get_arg_str(kw, "Text", "");
            let nickname = get_arg_str(kw, "NickName", "");
            let background = get_arg_str(kw, "Background", "");
            let text_color = get_arg_str(kw, "TextColor", "#FFFFFF");
            let speed = get_arg_i64(args, kw, 0, "Speed", 50);
            lan.post(
                "Voice/SendText",
                Some(json!({
                    "Text": text, "NickName": nickname, "Background": background,
                    "TextColor": text_color, "Speed": speed,
                })),
            )
            .await
        }

        // Danmaku scrolling bullet-chat overlay (docs/cloud_api/
        // vision_danmaku_game.md) — both in DeviceAndServerCmd, WiFi/HTTP
        // path (distinct from the BLE-only SendBlueText sibling). Not
        // GUI-wired: RandomFace has no confirmed caller anywhere in the
        // decompiled app (dead/unused in that build) and SendText needs the
        // same real-hardware render confirmation as Voice/SendText above.
        "lan.send_danmaku_text" => {
            let text = get_arg_str(kw, "Text", "");
            let text_color = get_arg_str(kw, "TextColor", "#FFFFFF");
            lan.post(
                "Danmaku/SendText",
                Some(json!({
                    "Text": text, "TextColor": text_color,
                })),
            )
            .await
        }
        "lan.danmaku_random_face" => lan.post("Danmaku/RandomFace", None).await,

        _ => return crate::protocol::err_reply(&format!("unknown LAN method: {method}")),
    };

    match res {
        Ok(val) => json!({ "success": true, "result": val }),
        Err(e) => crate::protocol::err_reply(&e.to_string()),
    }
}
