//! divoom-menubar — the native (Rust) menubar agent. A windowless tray app that
//! polls divoomd over the NDJSON socket for status + active devices and launches
//! the Python pywebview dashboard. Replaced the pyobjc menubar (removed in R66,
//! 2026-08-17); the desktop UI stays Python and the daemon stays Rust.
//!
//! Built on winit (event loop) + tray-icon. tray-icon needs an event loop on the
//! main thread; winit runs it via `run_app` with the `App` handler below. We
//! poll the daemon on a `WaitUntil` timer and forward tray/menu events through
//! the loop proxy.

mod daemon;
mod launch;
mod resubscribe;
mod state;
mod tiles;
mod tray;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use tray_icon::menu::MenuEvent;
use winit::application::ApplicationHandler;
use winit::event::{StartCause, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::WindowId;

use tray::{Tray, TrayAction};

/// Menu clicks forwarded into the loop so it wakes on interaction; `DaemonEvent`
/// wakes it EARLY (before the next POLL tick) on a live `status/owned_devices`
/// broadcast, so a connect/disconnect/degraded transition shows up promptly
/// instead of waiting up to POLL seconds. `poll_daemon()` still does the actual
/// state fetch + icon update on the main thread either way — this is purely
/// a wake-up signal, never touches the `TrayIcon` itself off-thread.
enum UserEvent {
    Menu(MenuEvent),
    DaemonEvent,
}

const POLL: Duration = Duration::from_secs(2);
// A dead/unreachable daemon shouldn't spin subscribe() in a tight reconnect
// loop; back off between attempts. Matches POLL's cadence roughly, so a
// daemon coming back up is noticed about as fast either way.
const SUBSCRIBE_RETRY_DELAY: Duration = Duration::from_secs(2);

const USAGE: &str = "\
divoom-menubar — the native Divoom tray agent.

USAGE:
    divoom-menubar [OPTIONS]

OPTIONS:
    -V, --version               print version and exit
    -h, --help                  print this help and exit

The agent takes no configuration: it polls divoomd on the default socket.";

/// What the caller should do, once the arguments have been read.
#[derive(Debug, PartialEq, Eq)]
enum CliOutcome {
    /// Run the tray agent.
    Run,
    /// Print this on stdout and exit 0.
    Print(String),
    /// Print this on stderr and exit 2.
    Refuse(String),
}

/// Read `argv` (WITHOUT the program name), BEFORE building an event loop and
/// claiming a tray slot.
///
/// This exists for the same reason `divoomd::cli_args` does:
/// `tools/check_built_binaries.py` has to be able to ask a built binary what
/// version it is, and the only honest answer is to print and exit. It also
/// closes the sibling of the divoomd defect — this binary accepted and ignored
/// every argument, so a mistyped flag silently launched a second tray icon.
///
/// The agent takes no configuration, so anything other than a lone `--version`
/// or `--help` is refused rather than ignored.
fn parse_cli(argv: &[String]) -> CliOutcome {
    if argv.is_empty() {
        return CliOutcome::Run;
    }
    if let [one] = argv {
        match one.as_str() {
            "--version" | "-V" => {
                return CliOutcome::Print(format!("divoom-menubar {}", env!("CARGO_PKG_VERSION")))
            }
            "--help" | "-h" => return CliOutcome::Print(USAGE.to_string()),
            _ => {}
        }
    }
    CliOutcome::Refuse(format!(
        "divoom-menubar: unexpected arguments {argv:?}\n\nRun `divoom-menubar --help` for usage."
    ))
}

fn main() {
    match parse_cli(&std::env::args().skip(1).collect::<Vec<_>>()) {
        CliOutcome::Print(msg) => {
            println!("{msg}");
            return;
        }
        CliOutcome::Refuse(msg) => {
            eprintln!("{msg}");
            std::process::exit(2);
        }
        CliOutcome::Run => {}
    }
    let mut builder = EventLoop::<UserEvent>::with_user_event();
    // macOS: run as a menubar agent (no Dock icon).
    #[cfg(target_os = "macos")]
    {
        use winit::platform::macos::{ActivationPolicy, EventLoopBuilderExtMacOS};
        builder.with_activation_policy(ActivationPolicy::Accessory);
    }
    let event_loop = builder
        .build()
        .expect("menubar event loop must build on the main thread");

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
                        |ev| {
                            daemon::update_snapshot_from_event(&ev);
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

    let mut app = App {
        tray: None,
        quitting,
    };

    event_loop
        .run_app(&mut app)
        .expect("menubar event loop must run on the main thread");
}

/// The winit `ApplicationHandler`: the same state machine tao's `run()` closure
/// used to hold as captures (`tray`, `quitting`), now as struct fields. Every
/// arm below mirrors the old closure arm-for-arm: tray creation on `Init`
/// (tray-icon issue #90 -- only once the loop is actually running), daemon
/// poll on each timer tick or live broadcast, quit tearing down the status
/// item first. Unhandled events leave the control flow untouched, so the
/// pending `WaitUntil` deadline survives them exactly as before.
struct App {
    tray: Option<Tray>,
    quitting: Arc<AtomicBool>,
}

impl App {
    /// Re-arm the daemon poll timer after every handled event.
    fn arm_poll_timer(event_loop: &ActiveEventLoop) {
        event_loop.set_control_flow(ControlFlow::WaitUntil(Instant::now() + POLL));
    }

    fn poll_daemon(&mut self) {
        if let Some(t) = self.tray.as_mut() {
            t.poll_daemon();
        }
    }
}

impl ApplicationHandler<UserEvent> for App {
    fn resumed(&mut self, _event_loop: &ActiveEventLoop) {
        // Windowless agent: nothing to create here. The tray is built in
        // `new_events(Init)` instead, once the loop is actually running.
    }

    fn window_event(
        &mut self,
        _event_loop: &ActiveEventLoop,
        _window_id: WindowId,
        _event: WindowEvent,
    ) {
        // Windowless agent: no windows, no window events.
    }

    fn new_events(&mut self, event_loop: &ActiveEventLoop, cause: StartCause) {
        match cause {
            // Create the tray once the loop is actually running (tray-icon issue #90).
            StartCause::Init => {
                self.tray = Tray::build();
                self.poll_daemon();
                macos_wake();
                Self::arm_poll_timer(event_loop);
            }
            // Timer tick → refresh status/devices.
            StartCause::ResumeTimeReached { .. } => {
                self.poll_daemon();
                Self::arm_poll_timer(event_loop);
            }
            _ => {}
        }
    }

    // A live daemon broadcast arrived — refresh now instead of
    // waiting for the next POLL tick.
    fn user_event(&mut self, event_loop: &ActiveEventLoop, event: UserEvent) {
        match event {
            UserEvent::DaemonEvent => {
                self.poll_daemon();
                Self::arm_poll_timer(event_loop);
            }
            UserEvent::Menu(ev) => {
                let quit = self
                    .tray
                    .as_mut()
                    .and_then(|t| t.on_menu(&ev))
                    .is_some_and(|a| matches!(a, TrayAction::Quit));
                if quit {
                    self.tray.take(); // drop the status item before exiting
                    self.quitting.store(true, Ordering::Relaxed); // let the subscribe thread exit
                    event_loop.exit();
                } else {
                    Self::arm_poll_timer(event_loop);
                }
            }
        }
    }
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

#[cfg(test)]
mod cli_tests {
    use super::*;

    fn argv(items: &[&str]) -> Vec<String> {
        items.iter().map(std::string::ToString::to_string).collect()
    }

    #[test]
    fn no_arguments_runs_the_agent() {
        assert_eq!(parse_cli(&argv(&[])), CliOutcome::Run);
    }

    #[test]
    fn version_prints_the_crate_version_and_does_not_run() {
        match parse_cli(&argv(&["--version"])) {
            CliOutcome::Print(m) => {
                assert!(m.starts_with("divoom-menubar "), "{m}");
                assert!(m.contains(env!("CARGO_PKG_VERSION")), "{m}");
            }
            other => panic!("expected Print, got {other:?}"),
        }
        assert!(matches!(parse_cli(&argv(&["-V"])), CliOutcome::Print(_)));
    }

    #[test]
    fn help_prints_usage() {
        for a in ["--help", "-h"] {
            match parse_cli(&argv(&[a])) {
                CliOutcome::Print(m) => assert!(m.contains("USAGE"), "{a}: {m}"),
                other => panic!("{a}: expected Print, got {other:?}"),
            }
        }
    }

    /// The agent takes no configuration, so an unrecognised flag was previously
    /// accepted and ignored — a typo silently started a second tray icon.
    #[test]
    fn unknown_arguments_are_refused_not_ignored() {
        match parse_cli(&argv(&["--socket", "/tmp/x.sock"])) {
            CliOutcome::Refuse(m) => assert!(m.contains("--socket"), "{m}"),
            other => panic!("expected Refuse, got {other:?}"),
        }
    }

    /// `--version` is only an answer when it is the WHOLE request; trailing
    /// arguments mean the caller expected something this binary cannot do.
    #[test]
    fn version_with_trailing_arguments_is_refused() {
        assert!(matches!(
            parse_cli(&argv(&["--version", "--nope"])),
            CliOutcome::Refuse(_)
        ));
    }
}
