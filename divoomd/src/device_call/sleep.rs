use super::rgb_triple;
use super::CallCtx;
use crate::device_call::pos_i64;
use crate::protocol::err_reply;
use crate::wire::WireNarrow as _;
use serde_json::{json, Value};

pub async fn handle(method: &str, ctx: CallCtx<'_>) -> Value {
    match method {
        "sleep.show_sleep" | "show_sleep" => show_sleep(ctx).await,
        "sleep.get_sleep_scene" | "get_sleep_scene" => get_sleep_scene(ctx).await,
        "sleep.set_sleep_scene_listen" | "set_sleep_scene_listen" => {
            set_sleep_scene_listen(ctx).await
        }
        "sleep.set_scene_volume" | "set_scene_volume" => set_scene_volume(ctx).await,
        "sound.set_sleep_color" | "sleep.set_sleep_color" | "set_sleep_color" => {
            set_sleep_color(ctx).await
        }
        "sleep.set_sleep_light" | "set_sleep_light" => set_sleep_light(ctx).await,
        "sleep.set_sleep_scene" | "set_sleep_scene" => set_sleep_scene(ctx).await,
        _ => err_reply("unimplemented sleep command"),
    }
}
async fn show_sleep(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    // R67/C7: these indices were read from the COMPACTED numeric list
    // and did not match the Python signature in either order or
    // position. `show_sleep` is
    //   (value, sleeptime, sleepmode, volume, color, brightness,
    //    frequency, on)
    //      0        1          2         3      4        5
    //                                                    6      7
    // so `color` is at 4 (it was read from 5) and every numeric was off
    // as soon as the caller passed `value` or `color` positionally.
    // Keyword callers were always fine, which is why this survived.
    let sleeptime = pos_i64(raw_args, 1, kw, "sleeptime", 60).byte();
    let sleepmode = pos_i64(raw_args, 2, kw, "sleepmode", 0).byte();
    let volume = pos_i64(raw_args, 3, kw, "volume", 16).byte();
    let frequency = pos_i64(raw_args, 6, kw, "frequency", 0).word();
    let on = pos_i64(raw_args, 7, kw, "on", 1).byte();
    let color_val = kw.and_then(|v| v.get("color")).or_else(|| raw_args.get(4));
    let [r, g, b] = rgb_triple(color_val);
    let brightness = pos_i64(raw_args, 5, kw, "brightness", 100).byte();

    let mut payload = Vec::with_capacity(10);
    payload.push(sleeptime);
    payload.push(sleepmode);
    payload.push(on);
    payload.extend_from_slice(&frequency.to_le_bytes());
    payload.push(volume);
    payload.push(r);
    payload.push(g);
    payload.push(b);
    payload.push(brightness);

    match dev.send_command(0x40, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("show_sleep failed: {e}")),
    }
}

async fn get_sleep_scene(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;

    match dev.send_command_and_wait(0xa2, &[], ctx.timeout).await {
        Some(p) if p.len() >= 10 => json!({
            "success": true,
            "result": {
                "time": i64::from(p[0]),
                "mode": i64::from(p[1]),
                "on": i64::from(p[2]),
                "fm_freq": i64::from(u16::from_le_bytes([p[3], p[4]])),
                "volume": i64::from(p[5]),
                "color_r": i64::from(p[6]),
                "color_g": i64::from(p[7]),
                "color_b": i64::from(p[8]),
                "light": i64::from(p[9]),
            }
        }),
        _ => json!({"success": true, "result": Value::Null}),
    }
}

async fn set_sleep_scene_listen(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let on_off = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("on_off"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let mode = args
        .get(1)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("mode"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    let volume = args
        .get(2)
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("volume"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    match dev.send_command(0xa3, &[on_off, mode, volume], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_sleep_scene_listen failed: {e}")),
    }
}

async fn set_scene_volume(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let volume = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("volume"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    match dev.send_command(0xa4, &[volume], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_scene_volume failed: {e}")),
    }
}

async fn set_sleep_color(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    let color_val = raw_args.first().or_else(|| kw.and_then(|v| v.get("color")));
    let [r, g, b] = rgb_triple(color_val);
    match dev.send_command(0xad, &[r, g, b], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_sleep_color failed: {e}")),
    }
}

async fn set_sleep_light(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let args = ctx.args;
    let kw = ctx.kwargs;

    let light = args
        .first()
        .copied()
        .or_else(|| {
            kw.and_then(|v| v.get("light"))
                .and_then(serde_json::Value::as_i64)
        })
        .unwrap_or(0)
        .byte();
    match dev.send_command(0xae, &[light], true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_sleep_light failed: {e}")),
    }
}

async fn set_sleep_scene(ctx: CallCtx<'_>) -> Value {
    let dev = ctx.dev;
    let raw_args = ctx.raw_args;
    let kw = ctx.kwargs;

    // R67/C7: fm_freq and color are LISTS, which the numeric list
    // drops — so `volume` (true position 3) was read as the 4th NUMBER
    // (which is `light`), and `light` fell off the end entirely.
    // Signature: (mode, on, fm_freq, volume, color, light).
    let mode = pos_i64(raw_args, 0, kw, "mode", 0).byte();
    let on = pos_i64(raw_args, 1, kw, "on", 0).byte();
    let fm_freq: Vec<u8> = raw_args
        .get(2)
        .and_then(|v| v.as_array())
        .or_else(|| kw.and_then(|v| v.get("fm_freq")).and_then(|v| v.as_array()))
        .map_or_else(
            || vec![0, 0],
            |a| {
                a.iter()
                    .filter_map(|x| x.as_u64().map(super::super::wire::WireNarrow::byte))
                    .collect()
            },
        );
    let fm_freq = if fm_freq.len() >= 2 {
        fm_freq
    } else {
        vec![0, 0]
    };
    let volume = pos_i64(raw_args, 3, kw, "volume", 0).byte();
    let color_val = raw_args.get(4).or_else(|| kw.and_then(|v| v.get("color")));
    let [r, g, b] = rgb_triple(color_val);
    let light = pos_i64(raw_args, 5, kw, "light", 0).byte();

    let mut payload = Vec::with_capacity(9);
    payload.push(mode);
    payload.push(on);
    payload.extend_from_slice(&fm_freq[0..2]);
    payload.push(volume);
    payload.push(r);
    payload.push(g);
    payload.push(b);
    payload.push(light);

    match dev.send_command(0x41, &payload, true).await {
        Ok(()) => json!({"success": true, "result": true}),
        Err(e) => err_reply(&format!("set_sleep_scene failed: {e}")),
    }
}
