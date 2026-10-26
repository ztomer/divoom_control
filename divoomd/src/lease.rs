//! Screen leases: an agent borrows a panel, then gives it back (P4.6).
//!
//! The nearest thing before this was `exclusive_start`/`exclusive_end` on the
//! command queue, and an agent drawing on a panel did not use it: its
//! `show_image` went through `preempt_conflicting_live_jobs`, which STOPPED
//! the panel's live widget for good -- and had it not, the widget's next frame
//! would have painted over the agent's. A crashed agent left its frame up
//! forever.
//!
//! A lease is the borrow, with the return built in:
//!
//! * `lease_acquire {mac?, ttl_ms, holder?}` takes the panel's queue for a
//!   bearer token (`CommandQueue::hold`) -- a call without the token is
//!   refused with `screen_leased`, naming the holder. The TTL is mandatory
//!   and bounded (`arg_bounds::LEASE_TTL_MS`); `lease_renew` moves it.
//! * The live job is PAUSED, not stopped: its frames keep rendering and are
//!   kept (`Device::save_job_frame`) instead of sent.
//! * When the lease ends -- released, or expired with nobody renewing -- the
//!   queue is let go and the job's newest frame is painted at once, so the
//!   panel is back to its widget without waiting for the job's next tick
//!   (weather ticks every 15 minutes). A panel with no live job is left
//!   showing the last thing drawn and the reply says `restored: "none"`:
//!   giving back the firmware channel waits on a panel to measure what 0x46
//!   reads after a pushed image (ROADMAP P9.7).
//! * Frame pushes conflate, leased or not: a queued push that is no longer
//!   the newest is skipped, so a fast agent on a slow link sees its latest
//!   frame, not a backlog.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::arg_bounds::LEASE_TTL_MS;
use crate::daemon::Daemon;
use crate::device::lease::Lease;
use crate::device::Device;
use crate::events::Events;
use crate::protocol::{err_code, ErrorCode, Request};

static GENERATION: AtomicU64 = AtomicU64::new(1);

fn ttl(req: &Request) -> Result<Duration, Value> {
    LEASE_TTL_MS
        .read(&req.args)
        .map(|ms| Duration::from_millis(u64::try_from(ms).unwrap_or(0)))
        .map_err(|e| err_code(ErrorCode::BadRequest, &format!("lease: {e}")))
}

fn ms(d: Duration) -> u64 {
    u64::try_from(d.as_millis()).unwrap_or(u64::MAX)
}

/// The panel whose lease `token` is.
async fn leased_device(daemon: &Daemon, token: &str) -> Option<Arc<Device>> {
    for d in daemon.fleet.all().await {
        if d.leased_to(token) {
            return Some(d);
        }
    }
    None
}

impl Daemon {
    pub(crate) async fn cmd_lease_acquire(&self, req: &Request) -> Value {
        let ttl = match ttl(req) {
            Ok(t) => t,
            Err(e) => return e,
        };
        let holder = req
            .args
            .get("holder")
            .and_then(Value::as_str)
            .unwrap_or("agent")
            .to_string();
        let mac = req.args.get("mac").and_then(Value::as_str);
        let device = match self.fleet.resolve_target(mac).await {
            Ok(d) => d,
            Err(e) => return e.reply(),
        };
        let Some(link) = device.link().await else {
            return err_code(ErrorCode::DeviceDisconnected, "panel is not linked");
        };
        if let Some(held) = device.lease() {
            return refused(&held);
        }
        let generation = GENERATION.fetch_add(1, Ordering::SeqCst);
        let token = format!(
            "lease-{generation}-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        );
        if let Err(e) = link.queue.hold(&token) {
            return err_code(ErrorCode::ScreenLeased, &e.to_string());
        }
        // A `disconnect` may have forgotten the panel since `resolve_target`:
        // no lease is granted on a panel that is gone (P5.9).
        let granted = device.set_lease(Lease {
            token: token.clone(),
            holder: holder.clone(),
            expires: Instant::now() + ttl,
            generation,
        });
        if granted.is_err() {
            link.queue.release(&token);
            return crate::device::Fleet::unknown(&device.id).reply();
        }
        tokio::spawn(watch(device.clone(), self.tx.clone(), generation));
        let _ = self.tx.send(json!({
            "type": "lease", "mac": device.id, "state": "acquired",
            "holder": holder, "ttl_ms": ms(ttl),
        }));
        json!({
            "success": true, "token": token, "mac": device.id,
            "holder": holder, "ttl_ms": ms(ttl),
        })
    }

    pub(crate) async fn cmd_lease_renew(&self, req: &Request) -> Value {
        let ttl = match ttl(req) {
            Ok(t) => t,
            Err(e) => return e,
        };
        let Some(token) = req.args.get("token").and_then(Value::as_str) else {
            return crate::command_args::missing("lease_renew", "'token'");
        };
        match leased_device(self, token).await {
            Some(d) if d.extend_lease(token, Instant::now() + ttl) => {
                json!({ "success": true, "mac": d.id, "ttl_ms": ms(ttl) })
            }
            _ => err_code(
                ErrorCode::LeaseExpired,
                "no such lease (it ended or never existed)",
            ),
        }
    }

    pub(crate) async fn cmd_lease_release(&self, req: &Request) -> Value {
        let Some(token) = req.args.get("token").and_then(Value::as_str) else {
            return crate::command_args::missing("lease_release", "'token'");
        };
        let Some(device) = leased_device(self, token).await else {
            return err_code(
                ErrorCode::LeaseExpired,
                "no such lease (it ended or never existed)",
            );
        };
        let Some(lease) = device.lease() else {
            return err_code(
                ErrorCode::LeaseExpired,
                "no such lease (it ended or never existed)",
            );
        };
        let restored = end(&device, &self.tx, lease.generation, "released").await;
        json!({ "success": true, "mac": device.id, "restored": restored })
    }
}

/// Whether this `device_call` draws a whole frame (the pushes that
/// conflate: a later one replaces an earlier one entirely).
pub(crate) fn is_frame_push(req: &Request) -> bool {
    let method = req.args.get("method").and_then(Value::as_str).unwrap_or("");
    method.rsplit('.').next() == Some("show_image")
}

/// The refusal a second caller gets: who holds it, and for how long more.
pub(crate) fn refused(held: &Lease) -> Value {
    let left = held.expires.saturating_duration_since(Instant::now());
    let mut reply = err_code(
        ErrorCode::ScreenLeased,
        &format!(
            "the screen is leased to {} for {} ms more",
            held.holder,
            ms(left)
        ),
    );
    reply["holder"] = json!(held.holder);
    reply["remaining_ms"] = json!(ms(left));
    reply
}

/// End lease `generation` on `device` once its time is up, unless it was
/// renewed (the end moved), released, or replaced meanwhile.
async fn watch(device: Arc<Device>, events: Arc<Events>, generation: u64) {
    loop {
        let Some(lease) = device.lease().filter(|l| l.generation == generation) else {
            return;
        };
        let now = Instant::now();
        if lease.expires <= now {
            end(&device, &events, generation, "expired").await;
            return;
        }
        tokio::time::sleep(lease.expires - now).await;
    }
}

/// Give the screen back: free the queue, repaint the live job's newest frame,
/// announce it. Returns what was restored (`"job"` or `"none"`).
async fn end(device: &Device, events: &Events, generation: u64, why: &str) -> &'static str {
    let Some(lease) = device.take_lease(generation) else {
        return "none";
    };
    let link = device.link().await;
    if let Some(link) = &link {
        link.queue.release(&lease.token);
    }
    let mut restored = "none";
    if let (Some(link), Some(kind), Some(frame)) =
        (link, device.live_kind().await, device.job_frame())
    {
        let link_in = link.clone();
        let repainted = (frame.rgb.clone(), frame.w, frame.h, frame.time_ms);
        let painted = link
            .run(None, async move {
                if link_in.is_retired() {
                    return false;
                }
                crate::live_jobs::push_rgb_to_device(
                    &link_in.transport,
                    &frame.rgb,
                    frame.w,
                    frame.h,
                    frame.time_ms,
                )
                .await
                .is_ok()
            })
            .await
            .unwrap_or(false);
        if painted {
            device.record_screen(crate::device::screen::Screen::of_frames(
                &kind,
                &[repainted],
            ));
            restored = "job";
        }
    }
    let _ = events.send(json!({
        "type": "lease", "mac": device.id, "state": why,
        "holder": lease.holder, "restored": restored,
    }));
    restored
}
