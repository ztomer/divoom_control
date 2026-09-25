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
        Outcome::Mcp => {
            if let Err(e) = divoomd::mcp::run().await {
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

    let daemon = Arc::new(Daemon::new());
    daemon.initialize_self_weak(Arc::downgrade(&daemon));

    // Monthly-best background sync is OPT-IN (parity: in Python it is a SEPARATE
    // daemon, not the main one). Without this gate the main daemon would push
    // gallery animations to every configured device on each startup. Enable with
    // DIVOOMD_MONTHLY_BEST=1.
    if matches!(
        std::env::var("DIVOOMD_MONTHLY_BEST").as_deref(),
        Ok("1" | "true" | "yes")
    ) {
        eprintln!("divoomd: monthly-best background sync enabled");
        tokio::spawn(divoomd::monthly_best::monthly_best_loop_task(
            daemon.clone(),
        ));
    }

    let max_connections = env_usize("DIVOOMD_MAX_CONNECTIONS", MAX_CONNECTIONS);
    let idle_timeout = env_duration("DIVOOMD_IDLE_TIMEOUT_SECS", CONNECTION_IDLE_TIMEOUT);
    eprintln!(
        "divoomd: socket limits — max_connections={max_connections}, idle_timeout={}s",
        idle_timeout.as_secs()
    );

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
