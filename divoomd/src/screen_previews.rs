//! `screen_previews`: what each panel is showing, as the daemon put it there
//! (WG.5a, "divoom control preview for each device").
//!
//! READ-ONLY. It reads the per-panel record `crate::device::screen` keeps and
//! sends nothing to any panel. The record is written where the pixels are
//! made and streamed -- a live job's frame (`live_jobs/frame.rs`), a lease
//! handing the screen back (`lease.rs`), a `device_call` image push (through
//! [`Sink`]), a wall push -- so a preview is the frames the panel took, never
//! a second rendering (house rule #9).
//!
//! Every panel the fleet holds gets an entry, and an entry with no frame says
//! WHY in `state` + `reason` (house rule #12): `offline` (no link),
//! `nothing_sent` (linked, but the daemon has not drawn on it since the link
//! came up), `device_rendered` (the panel draws it itself: a clock, a light,
//! text, a stored design or gallery page) or `undecoded` (a pre-encoded blob
//! the daemon streamed without decoding). Only `state: "frame"` carries
//! pixels. A transient notification overlay is not recorded: the panel goes
//! back to what it showed before it.

use serde_json::{json, Map, Value};

use crate::daemon::Daemon;
use crate::device::screen::{now_ms, Screen, Shown, Sink};
use crate::device::Device;
use crate::protocol::Request;

/// The `device_call` methods that stream bytes the daemon does not decode.
const UNDECODED_METHODS: &[&str] = &["stream_animation_8b", "push_animation", "send_image"];

/// `screen_previews {mac?}`: one entry per panel, or only `mac`'s.
pub(crate) async fn cmd_screen_previews(daemon: &Daemon, req: &Request) -> Value {
    let devices = match req.args.get("mac").and_then(Value::as_str) {
        Some(m) => match daemon.fleet.known(m).await {
            Ok(d) => vec![d],
            Err(e) => return e.reply(),
        },
        None => daemon.fleet.all().await,
    };
    let now = now_ms();
    let mut out = Vec::with_capacity(devices.len());
    for d in devices {
        out.push(entry(daemon, &d, now).await);
    }
    json!({ "success": true, "now_ms": now, "devices": out })
}

/// One panel's entry: who it is, how big, and what its screen shows.
async fn entry(daemon: &Daemon, d: &Device, now: u64) -> Value {
    let name = d.display_name().await;
    let listed = daemon.device_entry(d).await;
    let mut panel = listed.clone();
    if listed["width"].is_null() && !name.is_empty() {
        // An offline panel has no transport to ask: its last-known name.
        crate::daemon_status::merge(
            &mut panel,
            &crate::panel_model::from_name(Some(&name)).fields(),
        );
    }
    let connected = listed["connected"].as_bool() == Some(true);
    let mut e = Map::new();
    e.insert("id".into(), json!(d.id));
    e.insert("name".into(), json!(name));
    for k in ["connected", "selected"] {
        e.insert(k.into(), listed[k].clone());
    }
    for k in ["model", "width", "height", "model_source"] {
        e.insert(k.into(), panel[k].clone());
    }
    let screen = d.screen();
    let (state, reason) = state_of(connected, screen.as_ref());
    e.insert("state".into(), json!(state));
    e.insert("reason".into(), json!(reason));
    let frame = match screen.as_ref().map(|s| &s.shown) {
        Some(Shown::Frame {
            data_url,
            width,
            height,
            frames,
        }) if connected => json!({
            "data_url": data_url,
            "mime": data_url.strip_prefix("data:").and_then(|r| r.split(';').next()),
            "width": width,
            "height": height,
            "frames": frames,
        }),
        _ => Value::Null,
    };
    e.insert("frame".into(), frame);
    let (source, at, age) = match (&screen, connected) {
        (Some(s), true) => (
            json!(s.source),
            json!(s.at_ms),
            json!(
                f64::from(u32::try_from(now.saturating_sub(s.at_ms)).unwrap_or(u32::MAX)) / 1000.0
            ),
        ),
        _ => (Value::Null, Value::Null, Value::Null),
    };
    e.insert("source".into(), source);
    e.insert("at_ms".into(), at);
    e.insert("age_s".into(), age);
    Value::Object(e)
}

/// The entry's `state` and, for every state without pixels, why.
fn state_of(connected: bool, screen: Option<&Screen>) -> (&'static str, Option<String>) {
    if !connected {
        return (
            "offline",
            Some("the daemon has no link to this panel; what it shows now is unknown".into()),
        );
    }
    let Some(s) = screen else {
        return (
            "nothing_sent",
            Some(
                "linked, but the daemon has drawn nothing on it since the link came up; it \
                 shows whatever the panel or the vendor app last chose"
                    .into(),
            ),
        );
    };
    match s.shown {
        Shown::Frame { .. } => ("frame", None),
        Shown::DeviceRendered => (
            "device_rendered",
            Some(format!(
                "the panel draws this itself ({}); the daemon holds no pixels for it",
                s.source
            )),
        ),
        Shown::Undecoded => (
            "undecoded",
            Some(format!(
                "the daemon streamed bytes it did not decode ({}), so it cannot say which \
                 pixels they are",
                s.source
            )),
        ),
    }
}

/// The bare method name of a `device_call` request.
fn bare_method(req: &Request) -> &str {
    let method = req.args.get("method").and_then(Value::as_str).unwrap_or("");
    method.rsplit('.').next().unwrap_or(method)
}

/// Record what a successful `device_call` left on `device`'s screen: the
/// frames its handler streamed, else -- for a call that repaints -- that the
/// daemon holds no pixels for what is there now.
pub(crate) async fn after_device_call(device: &Device, req: &Request, sink: &Sink, repaints: bool) {
    let method = bare_method(req).to_string();
    if let Some(frames) = sink.take() {
        let screen = tokio::task::spawn_blocking(move || Screen::of_frames(&method, &frames))
            .await
            .ok();
        if let Some(s) = screen {
            device.record_screen(s);
        }
    } else if repaints {
        device.record_screen(no_pixels(&method));
    }
}

/// The record of a repaint the daemon has no pixels for.
fn no_pixels(method: &str) -> Screen {
    let shown = if UNDECODED_METHODS.contains(&method) {
        Shown::Undecoded
    } else {
        Shown::DeviceRendered
    };
    Screen::new(method, shown)
}

/// Record a wall call on each slot's panel: the cut a slot took for an image
/// push (`wall.previews`), else that the slot draws it itself.
pub(crate) async fn after_wall_call(daemon: &Daemon, req: &Request) {
    let method = bare_method(req).to_string();
    let image = matches!(method.as_str(), "show_image" | "display_image");
    let slots: Vec<(String, i32, i32, Option<String>)> = {
        let guard = daemon.wall.lock().await;
        let Some(wall) = guard.as_ref() else {
            return;
        };
        let slots = wall
            .devices
            .iter()
            .map(|s| {
                (
                    s.mac.clone(),
                    s.width.unwrap_or(s.size),
                    s.height.unwrap_or(s.size),
                    wall.previews.get(&s.mac),
                )
            })
            .collect();
        drop(guard);
        slots
    };
    for (mac, w, h, url) in slots {
        let Some(device) = daemon.fleet.get(&mac).await else {
            continue;
        };
        match (image, url) {
            (true, Some(url)) => device.record_screen(Screen::of_url(&method, Some(url), w, h)),
            // A slot whose image write failed keeps its record: it was not
            // repainted by this call.
            (true, None) => {}
            (false, _) => device.record_screen(no_pixels(&method)),
        }
    }
}

/// Record that an out-of-band writer (custom art, a hot channel, a gallery
/// page) is repainting `device` with something the daemon has no pixels for.
/// Called before the write: an unknown screen is the honest claim either way.
pub(crate) fn mark_device_rendered(device: &Device, source: &str) {
    device.record_screen(Screen::new(source, Shown::DeviceRendered));
}
