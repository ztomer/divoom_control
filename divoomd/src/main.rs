//! divoomd — the native daemon binary. Owns a unix socket and serves the NDJSON
//! protocol; it is the sole shipping daemon.
//!
//! The default socket is `/tmp/divoom.sock`, the same path every client uses.
//! It was `/tmp/divoomd.sock`, deliberately different so a Rust daemon could run
//! alongside the Python one during the port; that daemon was archived on
//! 2026-07-13 and removed in R66, so the divergence outlived its reason and left
//! a hand-started `divoomd` on a socket nothing could reach.
//! `tests/test_daemon_env_parity.py` compares the two defaults now.
//!
//!   divoomd [--socket /path/to.sock]
//!   divoomd <verb> [args]      set-volume, set-brightness, push-image, push-gif
//!
//! Argument parsing lives in `divoomd::cli_args` so it can be unit-tested in
//! both directions; this file is the shell that acts on the outcome.

use std::sync::Arc;
use std::time::Duration;

use divoomd::cli_args::{self, Outcome};
use divoomd::daemon::Daemon;
use tokio::net::UnixListener;

use divoomd::socket_server::{serve, serve_tcp, CONNECTION_IDLE_TIMEOUT, MAX_CONNECTIONS};

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key).map_or(default, |v| v.parse().unwrap_or(default))
}

fn env_duration(key: &str, default: Duration) -> Duration {
    std::env::var(key).map_or(default, |v| {
        v.parse::<u64>().map_or(default, Duration::from_secs)
    })
}

/// The socket limits from the environment, logged, with the wedge watchdog
/// started on the daemon's heartbeat.
///
/// P2.6: the accept loop beats `daemon.heartbeat`; a separate OS thread exits
/// the daemon once it has been silent past the bound, so the next client
/// respawns a daemon that serves instead of talking to one that cannot. The
/// report names who held the connections at the time. The thread runs for the
/// process's life, so its handle is dropped (detached) here.
fn serving_limits(daemon: &Daemon) -> (usize, Duration) {
    let max_connections = env_usize("DIVOOMD_MAX_CONNECTIONS", MAX_CONNECTIONS);
    let idle_timeout = env_duration("DIVOOMD_IDLE_TIMEOUT_SECS", CONNECTION_IDLE_TIMEOUT);
    let wedge_after = env_duration("DIVOOMD_WEDGE_SECS", divoomd::watchdog::WEDGE_AFTER);
    eprintln!(
        "divoomd: socket limits — max_connections={max_connections}, idle_timeout={}s, \
         wedge_after={}s",
        idle_timeout.as_secs(),
        wedge_after.as_secs()
    );
    drop(divoomd::watchdog::exit_when_wedged(
        daemon.heartbeat.clone(),
        daemon.connections.clone(),
        wedge_after,
    ));
    (max_connections, idle_timeout)
}

/// Bind the unix socket, or exit with the reason and the remedy.
///
/// Single-instance guard, stale-socket clearing and blocker diagnosis all
/// live in `socket_bind::acquire`, under an advisory lock so inspect-and-bind
/// is atomic against another daemon starting at the same moment. `held` owns
/// the listener, the startup lock and the identity of the file we bound;
/// keeping them in one value is what makes the shutdown ordering structural
/// instead of a comment -- see `socket_owner::HeldSocket`.
fn bind_unix(socket_path: &str) -> divoomd::socket_owner::HeldSocket<UnixListener> {
    let acquired = match divoomd::socket_bind::acquire(socket_path) {
        Ok(a) => a,
        Err(f) => {
            // Say it BOTH ways. stderr goes to the GUI's daemon log, which is
            // where a human looks; the sidecar file is what the client reads to
            // turn "no daemon" into an actual explanation.
            eprintln!("divoomd: {}", f.reason(socket_path));
            eprintln!("divoomd: {}", f.remedy());
            if f.describes_the_socket() {
                divoomd::socket_bind::write_failure(socket_path, &f);
            } else {
                // We lost the single-instance race, which means a HEALTHY
                // daemon owns this socket. Any sidecar sitting there is now
                // describing a condition that no longer holds, so clear it
                // rather than adding one — the winner cannot, since it never
                // re-enters acquire().
                divoomd::socket_bind::clear_failure(socket_path);
            }
            std::process::exit(f.exit_code());
        }
    };
    match acquired.into_held(|std_listener| {
        std_listener.set_nonblocking(true)?;
        UnixListener::from_std(std_listener)
    }) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("divoomd: cannot use {socket_path}: {e}");
            std::process::exit(1);
        }
    }
}

/// Bind the optional TCP listener: `None` when no host was given, the
/// listener and its required token otherwise. Exits when the request is
/// incomplete (no port, no token) or the bind fails.
async fn bind_tcp(
    host: Option<String>,
    port: Option<u16>,
    token: Option<String>,
) -> Option<(tokio::net::TcpListener, String)> {
    let host = host?;
    let Some(port) = port else {
        eprintln!("divoomd: TCP port is required when host is specified");
        std::process::exit(1);
    };
    let token = match token {
        Some(ref t) if !t.is_empty() => t.clone(),
        _ => {
            eprintln!("divoomd: TCP listener requested without a token; refusing to expose the daemon unauthenticated. Set DIVOOM_DAEMON_TOKEN or pass --token.");
            std::process::exit(1);
        }
    };
    let addr = format!("{host}:{port}");
    let l = match tokio::net::TcpListener::bind(&addr).await {
        Ok(listener) => listener,
        Err(e) => {
            eprintln!("divoomd: cannot bind TCP listener to {addr}: {e}");
            std::process::exit(1);
        }
    };
    eprintln!("divoomd listening on tcp://{addr} (token required)");
    Some((l, token))
}

#[tokio::main]
async fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let args = match cli_args::parse(&raw, std::env::var("DIVOOM_DAEMON_TOKEN").ok()) {
        // `--version` MUST answer without side effects: it is how the client and
        // the gates ask a built binary what it is, and a probe that starts a
        // daemon on the default socket is not a probe. Printed before any socket
        // work for that reason.
        Outcome::Version => {
            println!("divoomd {}", env!("CARGO_PKG_VERSION"));
            return;
        }
        Outcome::Help => {
            println!("{}", cli_args::USAGE);
            return;
        }
        Outcome::Error(msg) => {
            eprintln!("{msg}");
            std::process::exit(2);
        }
        // `divoomd mcp` runs the MCP stdio server (a client of the running
        // daemon), not the daemon itself. Ported from the Python
        // `divoom_lib.cli mcp-server`.
        Outcome::Mcp(options) => {
            if let Err(e) = divoomd::mcp::run(options).await {
                eprintln!("divoomd mcp: {e}");
                std::process::exit(1);
            }
            return;
        }
        // Device verbs are a CLIENT of a running daemon, like `mcp`: they
        // connect over the same target resolution and never open the radio.
        // Rendering lives here rather than in `verbs` so the module stays a
        // pure function of (request, target) and every output decision is in
        // one place.
        Outcome::Verb(request) => {
            let target = divoomd::daemon_target::DaemonTarget::from_env();
            match divoomd::verbs::run(&request, &target).await {
                Ok(outcome) => {
                    if request.json {
                        println!(
                            "{}",
                            serde_json::to_string_pretty(&outcome.value).unwrap_or_default()
                        );
                    } else {
                        println!("{}", outcome.human);
                    }
                }
                Err(e) => {
                    eprintln!("divoomd {}: {e}", request.verb.name());
                    std::process::exit(1);
                }
            }
            return;
        }
        Outcome::Run(cfg) => *cfg,
    };
    let socket_path = args.socket_path;
    let held = bind_unix(&socket_path);
    eprintln!("divoomd listening on {socket_path}");

    let tcp = bind_tcp(args.host, args.port, args.token).await;

    let daemon = start_daemon();

    // Monthly-best background sync.
    //
    // TWO switches, TWO owners, and they answer different questions:
    //
    // * `DIVOOM_MONTHLY_BEST=1` says "this process MAY run the scheduled
    //   push". The app sets it (divoom_gui/gui_main.py) because the app owns
    //   the schedule; a daemon spawned by a TEST, or by hand, does not get
    //   it — and that matters: the loop reaches the owner's panels, so a
    //   test daemon must never push to them or write their state.
    // * `hotchannel.json`'s `enabled` says "the push is ON, and every
    //   `interval` seconds" — the app's own Auto-Sync card, the same flag
    //   the Routines card shows and writes. The devices are the app's
    //   settings (`config.ini`'s `[gallery]` table).
    //
    // The environment used to be the ONLY switch, and nothing in this repo
    // ever set it, so the loop had never run in production: "enabled" was
    // true on paper and dead in fact.
    //
    // A daemon restart does not push: the loop waits out the remainder of
    // the interval (`monthly_best::should_run_now`).
    if matches!(
        std::env::var("DIVOOM_MONTHLY_BEST").as_deref(),
        Ok("1" | "true" | "yes")
    ) {
        eprintln!("divoomd: monthly-best background sync enabled");
        tokio::spawn(divoomd::monthly_best::monthly_best_loop_task(
            daemon.clone(),
        ));
    }

    let (max_connections, idle_timeout) = serving_limits(&daemon);

    // `held` keeps its own reference, so the socket outlives this future no
    // matter how the select below ends.
    let unix_fut = serve(
        held.listener(),
        daemon.clone(),
        max_connections,
        idle_timeout,
    );

    let shutdown = daemon.shutdown.clone();
    if let Some((l, t)) = tcp {
        let tcp_fut = serve_tcp(l, daemon.clone(), t, max_connections, idle_timeout);
        tokio::select! {
            () = unix_fut => {}
            () = tcp_fut => {}
            sig = shutdown_signal() => {
                eprintln!("divoomd: {sig} — shutting down");
            }
            () = shutdown.notified() => {
                eprintln!("divoomd: shutdown command — shutting down");
                // brief grace so the command's reply flushes to the client
                tokio::time::sleep(std::time::Duration::from_millis(150)).await;
            }
        }
    } else {
        tokio::select! {
            () = unix_fut => {}
            sig = shutdown_signal() => {
                eprintln!("divoomd: {sig} — shutting down");
            }
            () = shutdown.notified() => {
                eprintln!("divoomd: shutdown command — shutting down");
                tokio::time::sleep(std::time::Duration::from_millis(150)).await;
            }
        }
    }
    // Stop any in-flight BLE scan cleanly before exit so we don't leak a scan
    // session to bluetoothd (leaked sessions across restarts trip the OS
    // scan-frequency throttle → empty scans).
    #[cfg(feature = "ble")]
    daemon.stop_scan_cleanup().await;
    // Unlinks the socket only if it is still ours, with the listener necessarily
    // still open (`HeldSocket`'s `Drop` body runs before its fields are
    // dropped), then releases the startup lock. Explicit here because this
    // shutdown is deliberate; a panic or an early `exit` path gets the same
    // treatment from `Drop`.
    // The bool says whether the socket file was still ours. Nothing to do with
    // it here: `release` already PRINTS when it was not, which is the visible
    // symptom of a duplicate instance and the whole reason it is not silent.
    let _was_ours = held.release();
}

/// The daemon as the PROCESS runs it.
///
/// Two things are true of a daemon that runs and not of a `Daemon` value a
/// test builds:
///
///   * the panels it holds are written down, so they come back after a
///     restart (P2.7's remainder). Only the process asks for this: a test's
///     daemon keeps no list, so no test can write the user's — or erase it.
///   * the panels it held before it restarted are brought back. The GUI's own
///     relink covers the GUI's panels; this covers the ones a CLI or an MCP
///     client linked, and the wall's slots, which no client held in memory.
///     It runs on its own task, after a short delay, so the client that
///     started the daemon gets the radio first.
fn start_daemon() -> Arc<Daemon> {
    let mut daemon = Daemon::new();
    if let Some(location) = divoomd::links::resolve_location() {
        daemon.persist_links(location);
    }
    let daemon = Arc::new(daemon);
    daemon.initialize_self_weak(Arc::downgrade(&daemon));
    // The restore reaches for the radio, and the radio is what a daemon
    // WITHOUT the Bluetooth grant dies on (SIGABRT, no message). A daemon
    // started from a shell has no grant -- the grant belongs to the bundle
    // the app installed -- so the restore is opt-in: whoever spawns the
    // daemon with the grant (the app's client) asks for it.
    if restore_is_enabled() {
        let restore_daemon = daemon.clone();
        tokio::spawn(async move {
            divoomd::links::restore(&restore_daemon).await;
        });
    }
    daemon
}

/// Whether this daemon should bring its panels back at startup.
///
/// `DIVOOM_LINKS_RESTORE=1` asks for it. The app's client sets it, because
/// that is the spawn that carries the Bluetooth grant; a daemon started by
/// hand from a shell does not have the grant, and reaching for the radio
/// without it kills the process on the spot.
fn restore_is_enabled() -> bool {
    matches!(
        std::env::var("DIVOOM_LINKS_RESTORE").as_deref(),
        Ok("1" | "true" | "yes")
    )
}

/// Resolve when SIGINT or SIGTERM arrives, so the socket is unlinked on a clean
/// `kill` as well as Ctrl-C (the Python daemon handles both).
async fn shutdown_signal() -> &'static str {
    use tokio::signal::unix::{signal, SignalKind};
    let mut term = signal(SignalKind::terminate()).expect("install SIGTERM handler");
    tokio::select! {
        _ = tokio::signal::ctrl_c() => "SIGINT",
        _ = term.recv() => "SIGTERM",
    }
}
