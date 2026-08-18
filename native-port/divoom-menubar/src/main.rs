//! divoom-menubar — the native (Rust) menubar agent. A windowless tray app that
//! polls divoomd over the NDJSON socket for status + active devices and launches
//! the Python pywebview dashboard. Replaces the pyobjc menubar (`divoom_menubar/`)
//! while the desktop UI stays Python and the daemon stays Rust.
//!
//! Built on tao (event loop) + tray-icon. tray-icon needs an event loop on the
//! main thread; tao gives the classic run() closure. We poll the daemon on a
//! WaitUntil timer and forward tray/menu events through the loop proxy.

mod daemon;
mod launch;
mod resubscribe;
mod state;
mod tray;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use tao::event::{Event, StartCause};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tray_icon::menu::MenuEvent;

use tray::{Tray, TrayAction};

/// Menu clicks forwarded into the loop so it wakes on interaction; DaemonEvent
/// wakes it EARLY (before the next POLL tick) on a live status/owned_devices
/// broadcast, so a connect/disconnect/degraded transition shows up promptly
/// instead of waiting up to POLL seconds. poll_daemon() still does the actual
/// state fetch + icon update on the main thread either way — this is purely
/// a wake-up signal, never touches the TrayIcon itself off-thread.
enum UserEvent {
    Menu(MenuEvent),
    DaemonEvent,
}

const POLL: Duration = Duration::from_secs(2);
// A dead/unreachable daemon shouldn't spin subscribe() in a tight reconnect
// loop; back off between attempts. Matches POLL's cadence roughly, so a
// daemon coming back up is noticed about as fast either way.
const SUBSCRIBE_RETRY_DELAY: Duration = Duration::from_secs(2);

fn main() {
    // `set_activation_policy` below takes `&mut self`, and exists only on macOS,
    // so the binding is `mut` only there; on other targets it stays immutable
    // and `unused_mut` never fires.
    #[cfg(target_os = "macos")]
    let mut event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    #[cfg(not(target_os = "macos"))]
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    // macOS: run as a menubar agent (no Dock icon).
    #[cfg(target_os = "macos")]
    {
        use tao::platform::macos::{ActivationPolicy, EventLoopExtMacOS};
        event_loop.set_activation_policy(ActivationPolicy::Accessory);
    }

    // Forward menu events to the loop so it wakes on each click.
    let proxy = event_loop.create_proxy();
    MenuEvent::set_event_handler(Some(move |e| {
        let _ = proxy.send_event(UserEvent::Menu(e));
    }));

    // Background thread: subscribe to the daemon's live status/owned_devices
    // broadcast and wake the loop on every event (R61 follow-up). Reconnects
    // with a fixed backoff if the daemon is down/drops the stream — never
    // touches the TrayIcon itself, only nudges the loop to poll sooner.
    let quitting = Arc::new(AtomicBool::new(false));
    {
        let proxy = event_loop.create_proxy();
        let quitting = quitting.clone();
        thread::spawn(move || {
            // Loop body lives in resubscribe.rs so the "never die on a daemon
            // drop" guard (R53.39) is unit-testable — it was previously inline
            // here and therefore unreachable from any test.
            resubscribe::resubscribe_until_quit(
                || {
                    daemon::subscribe(
                        |_ev| {
                            let _ = proxy.send_event(UserEvent::DaemonEvent);
                        },
                        || quitting.load(Ordering::Relaxed),
                    );
                },
                || thread::sleep(SUBSCRIBE_RETRY_DELAY),
                || quitting.load(Ordering::Relaxed),
            );
        });
    }

    let mut tray: Option<Tray> = None;

    event_loop.run(move |event, _target, control_flow| {
        match event {
            // Create the tray once the loop is actually running (tray-icon issue #90).
            Event::NewEvents(StartCause::Init) => {
                tray = Tray::build();
                if let Some(t) = tray.as_mut() {
                    t.poll_daemon();
                }
                macos_wake();
                *control_flow = ControlFlow::WaitUntil(Instant::now() + POLL);
            }
            // Timer tick → refresh status/devices.
            Event::NewEvents(StartCause::ResumeTimeReached { .. }) => {
                if let Some(t) = tray.as_mut() {
                    t.poll_daemon();
                }
                *control_flow = ControlFlow::WaitUntil(Instant::now() + POLL);
            }
            // A live daemon broadcast arrived — refresh now instead of
            // waiting for the next POLL tick.
            Event::UserEvent(UserEvent::DaemonEvent) => {
                if let Some(t) = tray.as_mut() {
                    t.poll_daemon();
                }
                *control_flow = ControlFlow::WaitUntil(Instant::now() + POLL);
            }
            Event::UserEvent(UserEvent::Menu(ev)) => {
                let quit = tray
                    .as_mut()
                    .and_then(|t| t.on_menu(&ev))
                    .map(|a| matches!(a, TrayAction::Quit))
                    .unwrap_or(false);
                if quit {
                    tray.take(); // drop the status item before exiting
                    quitting.store(true, Ordering::Relaxed); // let the subscribe thread exit
                    *control_flow = ControlFlow::Exit;
                } else {
                    *control_flow = ControlFlow::WaitUntil(Instant::now() + POLL);
                }
            }
            _ => {}
        }
    })
}

/// macOS: nudge the main run loop so the status item paints on first show.
#[cfg(target_os = "macos")]
fn macos_wake() {
    use objc2_core_foundation::CFRunLoop;
    if let Some(rl) = CFRunLoop::main() {
        rl.wake_up();
    }
}

#[cfg(not(target_os = "macos"))]
fn macos_wake() {}
