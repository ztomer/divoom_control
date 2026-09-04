//! Drawing-pad / sand-paint / movie / scan subsystem — parity port of
//! `divoom_lib/display/drawing.py`. Low-level; not used by the GUI/MCP/CLI, ported
//! verbatim for device_call dispatch parity. Byte orders match Python exactly.
//!
//! NOTE (corrected R73): 0x35 DOES have an APK entry — `SPP_SCROLL(53)` in
//! `SppProc$CMD_TYPE.java`. The earlier note here, inherited from the R12
//! audit, said it had none; that audit was wrong, and it cited
//! `docs/PLANNING_ROUND12_D_AUDIT.md`, which no longer exists (pruned to git
//! history in b64c144 — a dangling citation nobody could check). The command
//! is real, its sole builder is `CmdManager.b3(mode, speed)`, and our bytes
//! match it exactly. See the `set_scroll` arm below. List args (offset_list/data/pic_data/image_data)
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
        // 0x35 is SPP_SCROLL(53) in the APK's command table, NOT the missing
        // opcode the R12 audit reported. Its only builder is CmdManager.b3:
        //
        //     b3(int mode, int speed) -> SPP_SCROLL,
        //         { 0, (byte) mode, (byte)(speed & 255), (byte)((speed >> 8) & 255) }
        //
        // Our control=0 arm reproduces those four bytes exactly (control IS the
        // leading constant 0). Verified on a Tivoo-Max, R73: accepted, no
        // visible change -- expected, because this SETS THE SCROLL MODE for
        // content the device is already scrolling, and nothing in this app ever
        // puts a device into a scrolling state (`push_text` rasterises a STATIC
        // image; see its docstring). It is not dead and it is not broken; it
        // has nothing to steer yet. Wire it when scrolling frames land.
        //
        // `control=1` ("image data") has NO counterpart anywhere in the APK --
        // b3 is the only SPP_SCROLL builder. It was invented by the Python lib
        // along with the `pic_scan_ctrl` name, and is removed here rather than
        // shipped as a second guess at a command we now have ground truth for.
        "drawing.set_scroll" | "set_scroll" | "drawing.pic_scan_ctrl" | "pic_scan_ctrl" => {
            // Refuse an under-specified call instead of defaulting to zeros.
            // `speed` defaulted to 0 is a no-op packet that still reported
            // success -- the same dishonesty as the sync_time year-2000 bug
            // R72 fixed, and it cost two invalid hardware runs this round
            // before anyone noticed the zeros.
            let (mode, speed) = match (kw_i64(kw, "mode"), kw_i64(kw, "speed")) {
                (Some(m), Some(s)) => (m, s),
                _ => {
                    return err_reply(
                        "set_scroll requires both `mode` and `speed`; refusing to \
                         send a zero-speed no-op and report it as success",
                    )
                }
            };
            if let Some(c) = kw_i64(kw, "control") {
                if c != 0 {
                    return err_reply(&format!(
                        "set_scroll: control={c} has no counterpart in the APK \
                         (CmdManager.b3 is the only SPP_SCROLL builder); only 0 is real"
                    ));
                }
            }
            let mut p = vec![0u8, mode as u8];
            p.extend_from_slice(&le16(speed));
            send(dev, 0x35, &p, "set_scroll").await
        }
        _ => err_reply("unimplemented drawing command"),
    }
}
