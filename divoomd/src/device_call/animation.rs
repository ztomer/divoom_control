//! Animation upload primitives — parity port of `divoom_lib/display/animation.py`
//! + `animation_user.py`. These are low-level gif/user-define chunk commands
//!   (the daemon's normal animation path is 0x8B streaming via show_image); ported
//!   verbatim for device_call dispatch parity. Byte orders match Python exactly.
//!
//! Data arrays (gif_data / file_data / data) arrive over device_call as JSON
//! arrays of u8 in `kwargs` (or positional `args`/`blobs[0]` for the big chunk).

use serde_json::{json, Map, Value};

use super::CallCtx;
use crate::daemon::DeviceTransport;
use crate::protocol::err_reply;

fn kw_i64(kw: Option<&Map<String, Value>>, name: &str) -> Option<i64> {
    kw.and_then(|m| m.get(name)).and_then(|v| v.as_i64())
}

/// Bytes from a kwarg: JSON array of u8, else empty.
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
fn le32(v: i64) -> [u8; 4] {
    (v as u32).to_le_bytes()
}
fn be32(v: i64) -> [u8; 4] {
    (v as u32).to_be_bytes()
}

async fn send(dev: &DeviceTransport, cmd: u8, payload: &[u8], label: &str) -> Value {
    match dev.send_command(cmd, payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("{label} failed: {e}")),
    }
}

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;
    // file_data/big chunk may arrive as blob[0]; prefer it over a kwargs array.
    let blob0 = ctx.blob_map.lock().unwrap().get(&0).cloned();
    let file_data = || -> Vec<u8> {
        if let Some(b) = &blob0 {
            b.clone()
        } else {
            kw_bytes(kw, "file_data")
        }
    };
    let cw = || -> i64 {
        args.first()
            .copied()
            .or_else(|| kw_i64(kw, "control_word"))
            .unwrap_or(0)
    };

    match method {
        "animation.set_gif_speed" | "set_gif_speed" => {
            let speed = args
                .first()
                .copied()
                .or_else(|| kw_i64(kw, "speed"))
                .unwrap_or(0);
            send(dev, 0x16, &le16(speed), "set_gif_speed").await
        }
        "animation.set_light_phone_gif" | "set_light_phone_gif" => {
            let total_len = kw_i64(kw, "total_len")
                .or_else(|| args.first().copied())
                .unwrap_or(0);
            let gif_id = kw_i64(kw, "gif_id")
                .or_else(|| args.get(1).copied())
                .unwrap_or(0);
            let mut p = Vec::new();
            p.extend_from_slice(&le16(total_len));
            p.push(gif_id as u8);
            p.extend_from_slice(&kw_bytes(kw, "gif_data"));
            send(dev, 0x49, &p, "set_light_phone_gif").await
        }
        "animation.set_rhythm_gif" | "set_rhythm_gif" => {
            send(dev, 0xb7, &rhythm_payload(args, kw), "set_rhythm_gif").await
        }
        "animation.app_send_eq_gif" | "app_send_eq_gif" => {
            send(dev, 0x1b, &rhythm_payload(args, kw), "app_send_eq_gif").await
        }
        // app_new_send_gif_cmd (0x8b): [cw] + START[file_size LE32] /
        // SENDING_DATA[file_size LE32, offset LE16, *file_data] / TERMINATE[].
        "animation.app_new_send_gif_cmd" | "app_new_send_gif_cmd" => {
            let cw = cw();
            let mut p = vec![cw as u8];
            match cw {
                0 => p.extend_from_slice(&le32(kw_i64(kw, "file_size").unwrap_or(0))),
                1 => {
                    p.extend_from_slice(&le32(kw_i64(kw, "file_size").unwrap_or(0)));
                    p.extend_from_slice(&le16(kw_i64(kw, "file_offset_id").unwrap_or(0)));
                    p.extend_from_slice(&file_data());
                }
                2 => {}
                _ => return err_reply(&format!("app_new_send_gif_cmd: unknown control word {cw}")),
            }
            send(dev, 0x8b, &p, "app_new_send_gif_cmd").await
        }
        // set_user_gif (0xb1): [cw] + SUG handlers.
        "animation.set_user_gif" | "set_user_gif" => {
            let cw = cw();
            let mut p = vec![cw as u8];
            match cw {
                0 | 2 => {
                    // START_SAVING / TRANSMISSION_END: data[0] selects sub-format.
                    let data = kw_bytes(kw, "data");
                    if data.is_empty() {
                        return err_reply("set_user_gif: missing 'data'");
                    }
                    p.push(data[0]);
                    match data[0] {
                        1 => {
                            // LED editor: [type, speed, text_length, *data[3:]]
                            let (speed, tl) = match (kw_i64(kw, "speed"), kw_i64(kw, "text_length"))
                            {
                                (Some(s), Some(t)) if data.len() >= 3 => (s, t),
                                _ => {
                                    return err_reply(
                                        "set_user_gif: LED editor needs speed+text_length",
                                    )
                                }
                            };
                            p.push(speed as u8);
                            p.push(tl as u8);
                            p.extend_from_slice(&data[3..]);
                        }
                        3 => {
                            // Scroll animation: [type, mode, speed LE16, len LE16]
                            let (mode, speed, len_val) = match (
                                kw_i64(kw, "mode"),
                                kw_i64(kw, "speed"),
                                kw_i64(kw, "len_val"),
                            ) {
                                (Some(m), Some(s), Some(l)) => (m, s, l),
                                _ => {
                                    return err_reply(
                                        "set_user_gif: scroll needs mode+speed+len_val",
                                    )
                                }
                            };
                            p.push(mode as u8);
                            p.extend_from_slice(&le16(speed));
                            p.extend_from_slice(&le16(len_val));
                        }
                        _ => {}
                    }
                }
                1 => {
                    // TRANSMIT_DATA: [len(data) LE16, *data]
                    let data = kw_bytes(kw, "data");
                    if data.len() < 2 {
                        return err_reply("set_user_gif: transmit needs >=2 data bytes");
                    }
                    p.extend_from_slice(&le16(data.len() as i64));
                    p.extend_from_slice(&data);
                }
                _ => return err_reply(&format!("set_user_gif: unknown control word {cw}")),
            }
            send(dev, 0xb1, &p, "set_user_gif").await
        }
        // app_new_user_define (0x8c): [cw] + ANUD handlers.
        "animation.app_new_user_define" | "app_new_user_define" => {
            let cw = cw();
            let mut p = vec![cw as u8];
            match cw {
                0 => {
                    p.extend_from_slice(&le32(kw_i64(kw, "file_size").unwrap_or(0)));
                    p.push(kw_i64(kw, "index").unwrap_or(0) as u8);
                }
                1 => {
                    p.extend_from_slice(&le32(kw_i64(kw, "file_size").unwrap_or(0)));
                    p.extend_from_slice(&le16(kw_i64(kw, "file_offset_id").unwrap_or(0)));
                    p.extend_from_slice(&file_data());
                }
                2 => {}
                _ => return err_reply(&format!("app_new_user_define: unknown control word {cw}")),
            }
            send(dev, 0x8c, &p, "app_new_user_define").await
        }
        // app_big64_user_define (0x8d): [cw] + ABUD handlers.
        "animation.app_big64_user_define" | "app_big64_user_define" => {
            let cw = cw();
            let mut p = vec![cw as u8];
            match cw {
                0 => {
                    p.extend_from_slice(&le32(kw_i64(kw, "file_size").unwrap_or(0)));
                    p.push(kw_i64(kw, "index").unwrap_or(0) as u8);
                    p.extend_from_slice(&be32(kw_i64(kw, "file_id").unwrap_or(0)));
                }
                1 => {
                    p.extend_from_slice(&le32(kw_i64(kw, "file_size").unwrap_or(0)));
                    p.extend_from_slice(&le16(kw_i64(kw, "file_offset_id").unwrap_or(0)));
                    p.extend_from_slice(&file_data());
                }
                2 => {}
                3 | 4 => {
                    // DELETE / PLAY_ARTWORK: [file_id BE32, index]
                    p.extend_from_slice(&be32(kw_i64(kw, "file_id").unwrap_or(0)));
                    p.push(kw_i64(kw, "index").unwrap_or(0) as u8);
                }
                5 => p.push(kw_i64(kw, "index").unwrap_or(0) as u8), // DELETE_ALL_BY_INDEX
                _ => {
                    return err_reply(&format!("app_big64_user_define: unknown control word {cw}"))
                }
            }
            send(dev, 0x8d, &p, "app_big64_user_define").await
        }
        // modify_user_gif_items (0xb6) read-back: [data] -> response[0].
        "animation.modify_user_gif_items" | "modify_user_gif_items" => {
            let data = args
                .first()
                .copied()
                .or_else(|| kw_i64(kw, "data"))
                .unwrap_or(0);
            match dev
                .send_command_and_wait(0xb6, &[data as u8], ctx.timeout)
                .await
            {
                Some(r) if !r.is_empty() => json!({"success": true, "result": r[0] as i64}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        // app_get_user_define_info (0x8e) read-back: [user_index] -> parsed dict.
        // Hardware-tested 2026-07-13 on a real Ditoo: the device never replied
        // (0x8e query timed out at the daemon's outer per-call timeout, ~30s)
        // — no crash, no wedge, device stayed connected/responsive to
        // subsequent calls after. Inconclusive on whether 0x8e itself is
        // supported on this model, or there's simply no saved custom-GIF
        // slot at user_index=0 to report; the graceful `Some(r) if
        // !r.is_empty()` / `_ => null` handling below never actually gets
        // exercised in that case because the daemon's OWN outer call-timeout
        // wrapper fires first and returns a hard error instead of letting
        // send_command_and_wait's None resolve into the intended graceful
        // null result — worth a closer look if this command is picked up for
        // real use.
        "animation.app_get_user_define_info" | "app_get_user_define_info" => {
            let idx = args
                .first()
                .copied()
                .or_else(|| kw_i64(kw, "user_index"))
                .unwrap_or(0);
            match dev
                .send_command_and_wait(0x8e, &[idx as u8], ctx.timeout)
                .await
            {
                Some(r) if !r.is_empty() => {
                    json!({"success": true, "result": parse_user_define_info(&r)})
                }
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        _ => err_reply("unimplemented animation command"),
    }
}

/// pos(1 BE) + total_length(2 LE) + gif_id(1 BE) + *data — shared by set_rhythm_gif
/// (0xb7) and app_send_eq_gif (0x1b).
fn rhythm_payload(args: &[i64], kw: Option<&Map<String, Value>>) -> Vec<u8> {
    let pos = kw_i64(kw, "pos")
        .or_else(|| args.first().copied())
        .unwrap_or(0);
    let total_length = kw_i64(kw, "total_length")
        .or_else(|| args.get(1).copied())
        .unwrap_or(0);
    let gif_id = kw_i64(kw, "gif_id")
        .or_else(|| args.get(2).copied())
        .unwrap_or(0);
    let mut p = vec![pos as u8];
    p.extend_from_slice(&le16(total_length));
    p.push(gif_id as u8);
    p.extend_from_slice(&kw_bytes(kw, "data"));
    p
}

fn parse_user_define_info(r: &[u8]) -> Value {
    let cw = r[0];
    if cw == 1 && r.len() >= 8 {
        let num = u16::from_le_bytes([r[6], r[7]]) as usize;
        let mut file_ids = Vec::new();
        for i in 0..num {
            let s = 8 + i * 4;
            if r.len() >= s + 4 {
                file_ids.push(u32::from_be_bytes([r[s], r[s + 1], r[s + 2], r[s + 3]]) as i64);
            }
        }
        json!({
            "control_word": cw, "user_index": r[1],
            "total": u16::from_le_bytes([r[2], r[3]]),
            "offset": u16::from_le_bytes([r[4], r[5]]),
            "num": num, "file_ids": file_ids,
        })
    } else if cw == 2 && r.len() >= 2 {
        json!({"control_word": cw, "user_index": r[1]})
    } else {
        Value::Null
    }
}
