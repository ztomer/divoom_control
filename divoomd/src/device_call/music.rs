//! SD-card music control — parity port of `divoom_lib/media/music.py` (the SD/play
//! methods not already in basic.rs). Setters + read-backs; command ids + response
//! offsets taken verbatim from the Python source.

use serde_json::{json, Map, Value};

use super::CallCtx;
use crate::protocol::err_reply;

fn kw_i64(kw: Option<&Map<String, Value>>, name: &str) -> Option<i64> {
    kw.and_then(|m| m.get(name)).and_then(|v| v.as_i64())
}
fn le16(v: i64) -> [u8; 2] {
    (v as u16).to_le_bytes()
}

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;
    let to = ctx.timeout;
    let arg0 = |name: &str| args.first().copied().or_else(|| kw_i64(kw, name));

    let ok = |r: Result<(), String>, label: &str| match r {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("{label} failed: {e}")),
    };

    match method {
        // ── setters ────────────────────────────────────────────────────────
        "music.app_need_get_music_list" | "app_need_get_music_list" => ok(
            dev.send_command(0x47, &[], true)
                .await
                .map_err(|e| e.to_string()),
            "app_need_get_music_list",
        ),
        "music.send_sd_list_over" | "send_sd_list_over" => ok(
            dev.send_command(0x14, &[], true)
                .await
                .map_err(|e| e.to_string()),
            "send_sd_list_over",
        ),
        "music.set_play_status" | "set_play_status" => {
            let s = arg0("status").unwrap_or(0) as u8;
            ok(
                dev.send_command(0x0a, &[s], true)
                    .await
                    .map_err(|e| e.to_string()),
                "set_play_status",
            )
        }
        "music.set_sd_last_next" | "set_sd_last_next" => {
            let a = arg0("action").unwrap_or(0) as u8;
            ok(
                dev.send_command(0x12, &[a], true)
                    .await
                    .map_err(|e| e.to_string()),
                "set_sd_last_next",
            )
        }
        "music.set_sd_music_play_mode" | "set_sd_music_play_mode" => {
            let pm = arg0("play_mode").unwrap_or(0) as u8;
            ok(
                dev.send_command(0xb9, &[pm], true)
                    .await
                    .map_err(|e| e.to_string()),
                "set_sd_music_play_mode",
            )
        }
        "music.set_sd_music_position" | "set_sd_music_position" => {
            let pos = arg0("position").unwrap_or(0);
            ok(
                dev.send_command(0xb8, &le16(pos), true)
                    .await
                    .map_err(|e| e.to_string()),
                "set_sd_music_position",
            )
        }
        "music.set_sd_play_music_id" | "set_sd_play_music_id" => {
            let id = arg0("music_id").unwrap_or(0);
            ok(
                dev.send_command(0x11, &le16(id), true)
                    .await
                    .map_err(|e| e.to_string()),
                "set_sd_play_music_id",
            )
        }
        "music.set_sd_music_info" | "set_sd_music_info" => {
            let cur = kw_i64(kw, "current_time")
                .or_else(|| args.first().copied())
                .unwrap_or(0);
            let mid = kw_i64(kw, "music_id")
                .or_else(|| args.get(1).copied())
                .unwrap_or(0);
            let vol = kw_i64(kw, "volume")
                .or_else(|| args.get(2).copied())
                .unwrap_or(0) as u8;
            let st = kw_i64(kw, "status")
                .or_else(|| args.get(3).copied())
                .unwrap_or(0) as u8;
            let pm = kw_i64(kw, "play_mode")
                .or_else(|| args.get(4).copied())
                .unwrap_or(0) as u8;
            let mut p = Vec::new();
            p.extend_from_slice(&le16(cur));
            p.extend_from_slice(&le16(mid));
            p.push(vol);
            p.push(st);
            p.push(pm);
            ok(
                dev.send_command(0xb5, &p, true)
                    .await
                    .map_err(|e| e.to_string()),
                "set_sd_music_info",
            )
        }

        // ── read-backs ─────────────────────────────────────────────────────
        "music.get_play_status" | "get_play_status" => {
            match dev.send_command_and_wait(0x0b, &[], to).await {
                Some(r) if !r.is_empty() => json!({"success": true, "result": r[0] as i64}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "music.get_sd_music_list_total_num" | "get_sd_music_list_total_num" => {
            match dev.send_command_and_wait(0x7d, &[], to).await {
                Some(r) if r.len() >= 2 => {
                    json!({"success": true, "result": u16::from_le_bytes([r[0], r[1]]) as i64})
                }
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "music.get_sd_music_info" | "get_sd_music_info" => {
            match dev.send_command_and_wait(0xb4, &[], to).await {
                Some(r) if r.len() >= 9 => json!({"success": true, "result": {
                    "current_time": u16::from_le_bytes([r[0], r[1]]),
                    "total_time": u16::from_le_bytes([r[2], r[3]]),
                    "music_id": u16::from_le_bytes([r[4], r[5]]),
                    "status": r[6], "volume": r[7], "play_mode": r[8],
                }}),
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "music.get_sd_play_name" | "get_sd_play_name" => {
            match dev.send_command_and_wait(0x06, &[], to).await {
                Some(r) if r.len() >= 2 => {
                    let n = u16::from_le_bytes([r[0], r[1]]) as usize;
                    if r.len() >= 2 + n {
                        json!({"success": true, "result": String::from_utf8_lossy(&r[2..2 + n])})
                    } else {
                        json!({"success": true, "result": Value::Null})
                    }
                }
                _ => json!({"success": true, "result": Value::Null}),
            }
        }
        "music.get_sd_music_list" | "get_sd_music_list" => {
            let start = kw_i64(kw, "start_id")
                .or_else(|| args.first().copied())
                .unwrap_or(0);
            let end = kw_i64(kw, "end_id")
                .or_else(|| args.get(1).copied())
                .unwrap_or(0);
            let mut req = Vec::new();
            req.extend_from_slice(&le16(start));
            req.extend_from_slice(&le16(end));
            match dev.send_command_and_wait(0x07, &req, to).await {
                Some(r) => {
                    let mut list = Vec::new();
                    let mut off = 0usize;
                    while off + 4 <= r.len() {
                        let id = u16::from_le_bytes([r[off], r[off + 1]]);
                        off += 2;
                        let name_len = u16::from_le_bytes([r[off], r[off + 1]]) as usize;
                        off += 2;
                        if off + name_len <= r.len() {
                            let name = String::from_utf8_lossy(&r[off..off + name_len]).to_string();
                            list.push(json!({"id": id, "name": name}));
                            off += name_len;
                        } else {
                            break;
                        }
                    }
                    json!({"success": true, "result": list})
                }
                _ => json!({"success": true, "result": []}),
            }
        }
        _ => err_reply("unimplemented music command"),
    }
}
