//! Drawing-pad / sand-paint / movie / scan subsystem — parity port of
//! `divoom_lib/display/drawing.py`. Low-level; not used by the GUI/MCP/CLI, ported
//! verbatim for device_call dispatch parity. Byte orders match Python exactly.
//!
//! NOTE: `pic_scan_ctrl` (0x35) has no entry in the decompiled APK's command
//! table (see docs/PLANNING_ROUND12_D_AUDIT.md); ported to match the Python
//! lib, which may itself be wrong. Hardware-tested 2026-07-13 on a real
//! Pixoo-1: both control=0 and control=1 GATT writes ACK cleanly (no
//! rejection/disconnect), device stays responsive after. Transport-level
//! confirmation only — ACK != device-confirmed semantic handling (a firmware
//! can silently ACK-and-drop an unrecognized opcode); no visual on-device
//! effect was confirmed. List args (offset_list/data/pic_data/image_data)
//! arrive as JSON arrays in kwargs (or blobs[0] for the big chunk).

use serde_json::{json, Map, Value};

use super::CallCtx;
use crate::daemon::DeviceTransport;
use crate::protocol::err_reply;

fn kw_i64(kw: Option<&Map<String, Value>>, name: &str) -> Option<i64> {
    kw.and_then(|m| m.get(name)).and_then(|v| v.as_i64())
}
fn kw_bytes(kw: Option<&Map<String, Value>>, name: &str) -> Vec<u8> {
    kw.and_then(|m| m.get(name))
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_u64().map(|n| n as u8))
                .collect()
        })
        .unwrap_or_default()
}
fn le16(v: i64) -> [u8; 2] {
    (v as u16).to_le_bytes()
}

async fn send(dev: &DeviceTransport, cmd: u8, p: &[u8], label: &str) -> Value {
    match dev.send_command(cmd, p, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("{label} failed: {e}")),
    }
}

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let kw = ctx.kwargs;
    let i = |n: &str, d: i64| kw_i64(kw, n).unwrap_or(d);
    // big data may come as blob[0]
    let blob0 = ctx.blob_map.lock().unwrap().get(&0).cloned();
    let data = |name: &str| -> Vec<u8> {
        if let Some(b) = &blob0 {
            b.clone()
        } else {
            kw_bytes(kw, name)
        }
    };

    match method {
        "drawing.set_light_pic" | "set_light_pic" => {
            send(dev, 0x44, &data("pic_data"), "set_light_pic").await
        }
        "drawing.drawing_pad_exit" | "drawing_pad_exit" => {
            send(dev, 0x5a, &[], "drawing_pad_exit").await
        }
        "drawing.drawing_mul_encode_gif_play" | "drawing_mul_encode_gif_play" => {
            send(dev, 0x6b, &[], "drawing_mul_encode_gif_play").await
        }
        "drawing.drawing_ctrl_movie_play" | "drawing_ctrl_movie_play" => {
            send(
                dev,
                0x6e,
                &[i("control_command", 0) as u8],
                "drawing_ctrl_movie_play",
            )
            .await
        }
        "drawing.drawing_mul_pad_enter" | "drawing_mul_pad_enter" => {
            send(
                dev,
                0x6f,
                &[i("r", 0) as u8, i("g", 0) as u8, i("b", 0) as u8],
                "drawing_mul_pad_enter",
            )
            .await
        }
        "drawing.drawing_pad_ctrl" | "drawing_pad_ctrl" => {
            let mut p = vec![
                i("r", 0) as u8,
                i("g", 0) as u8,
                i("b", 0) as u8,
                i("num_points", 0) as u8,
            ];
            p.extend_from_slice(&kw_bytes(kw, "offset_list"));
            send(dev, 0x58, &p, "drawing_pad_ctrl").await
        }
        "drawing.drawing_mul_pad_ctrl" | "drawing_mul_pad_ctrl" => {
            let mut p = vec![
                i("screen_id", 0) as u8,
                i("r", 0) as u8,
                i("g", 0) as u8,
                i("b", 0) as u8,
                i("num_points", 0) as u8,
            ];
            p.extend_from_slice(&kw_bytes(kw, "offset_list"));
            send(dev, 0x3a, &p, "drawing_mul_pad_ctrl").await
        }
        "drawing.drawing_big_pad_ctrl" | "drawing_big_pad_ctrl" => {
            let mut p = vec![
                i("canvas_width", 0) as u8,
                i("screen_id", 0) as u8,
                i("r", 0) as u8,
                i("g", 0) as u8,
                i("b", 0) as u8,
                i("num_points", 0) as u8,
            ];
            p.extend_from_slice(&kw_bytes(kw, "offset_list"));
            send(dev, 0x3b, &p, "drawing_big_pad_ctrl").await
        }
        "drawing.drawing_mul_encode_single_pic" | "drawing_mul_encode_single_pic" => {
            let mut p = vec![i("screen_id", 0) as u8];
            p.extend_from_slice(&le16(i("data_length", 0)));
            p.extend_from_slice(&data("data"));
            send(dev, 0x5b, &p, "drawing_mul_encode_single_pic").await
        }
        "drawing.drawing_mul_encode_pic" | "drawing_mul_encode_pic" => {
            let mut p = vec![i("screen_id", 0) as u8];
            p.extend_from_slice(&le16(i("total_length", 0)));
            p.push(i("pic_id", 0) as u8);
            p.extend_from_slice(&data("pic_data"));
            send(dev, 0x5c, &p, "drawing_mul_encode_pic").await
        }
        "drawing.drawing_encode_movie_play" | "drawing_encode_movie_play" => {
            let mut p = Vec::new();
            p.extend_from_slice(&le16(i("frame_id", 0)));
            p.extend_from_slice(&le16(i("data_length", 0)));
            p.extend_from_slice(&data("data"));
            send(dev, 0x6c, &p, "drawing_encode_movie_play").await
        }
        "drawing.drawing_mul_encode_movie_play" | "drawing_mul_encode_movie_play" => {
            let mut p = vec![i("screen_id", 0) as u8];
            p.extend_from_slice(&le16(i("frame_id", 0)));
            p.extend_from_slice(&le16(i("data_length", 0)));
            p.extend_from_slice(&data("data"));
            send(dev, 0x6d, &p, "drawing_mul_encode_movie_play").await
        }
        // sand_paint_ctrl (0x34): [control] + INITIALIZE[device_id, image_length LE16, *image_data] / RESET[].
        "drawing.sand_paint_ctrl" | "sand_paint_ctrl" => {
            let control = i("control", 0);
            let mut p = vec![control as u8];
            match control {
                0 => {
                    p.push(i("device_id", 0) as u8);
                    p.extend_from_slice(&le16(i("image_length", 0)));
                    p.extend_from_slice(&data("image_data"));
                }
                1 => {}
                _ => return err_reply(&format!("sand_paint_ctrl: unknown control {control}")),
            }
            send(dev, 0x34, &p, "sand_paint_ctrl").await
        }
        // pic_scan_ctrl (0x35, UNVERIFIED): [control] + MODE_SPEED[mode, speed LE16] / IMAGE_DATA[total_length LE16, pic_id, *data].
        "drawing.pic_scan_ctrl" | "pic_scan_ctrl" => {
            let control = i("control", 0);
            let mut p = vec![control as u8];
            match control {
                0 => {
                    p.push(i("mode", 0) as u8);
                    p.extend_from_slice(&le16(i("speed", 0)));
                }
                1 => {
                    p.extend_from_slice(&le16(i("total_length", 0)));
                    p.push(i("pic_id", 0) as u8);
                    p.extend_from_slice(&data("data"));
                }
                _ => return err_reply(&format!("pic_scan_ctrl: unknown control {control}")),
            }
            send(dev, 0x35, &p, "pic_scan_ctrl").await
        }
        _ => err_reply("unimplemented drawing command"),
    }
}
