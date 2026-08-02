//! divoomd — the native daemon binary. Owns a unix socket and serves the NDJSON
//! protocol. Runs in parallel to the Python daemon (default socket
//! `/tmp/divoomd.sock`, distinct from the Python `/tmp/divoom.sock`) so both can
//! coexist during the port. See docs/ROADMAP.md.
//!
//!   divoomd [--socket /path/to.sock]

use std::sync::Arc;
use std::time::Duration;

use divoomd::daemon::Daemon;
use tokio::net::UnixListener;

struct ConfigArgs {
    socket_path: String,
    host: Option<String>,
    port: Option<u16>,
    token: Option<String>,
    mac: Option<String>,
}

fn parse_args() -> ConfigArgs {
    let args: Vec<String> = std::env::args().collect();
    let mut socket_path = "/tmp/divoomd.sock".to_string();
    let mut host = None;
    let mut port = None;
    let mut token = std::env::var("DIVOOM_DAEMON_TOKEN").ok();
    let mut mac = None;

    let mut i = 1;
    while i < args.len() {
        if let Some(p) = args[i].strip_prefix("--socket=") {
            socket_path = p.to_string();
        } else if args[i] == "--socket" && i + 1 < args.len() {
            socket_path = args[i + 1].clone();
            i += 1;
        } else if let Some(h) = args[i].strip_prefix("--host=") {
            host = Some(h.to_string());
        } else if args[i] == "--host" && i + 1 < args.len() {
            host = Some(args[i + 1].clone());
            i += 1;
        } else if let Some(p) = args[i].strip_prefix("--port=") {
            port = p.parse().ok();
        } else if args[i] == "--port" && i + 1 < args.len() {
            port = args[i + 1].parse().ok();
            i += 1;
        } else if let Some(t) = args[i].strip_prefix("--token=") {
            token = Some(t.to_string());
        } else if args[i] == "--token" && i + 1 < args.len() {
            token = Some(args[i + 1].clone());
            i += 1;
        } else if let Some(m) = args[i].strip_prefix("--mac=") {
            mac = Some(m.to_string());
        } else if args[i] == "--mac" && i + 1 < args.len() {
            mac = Some(args[i + 1].clone());
            i += 1;
        }
        i += 1;
    }

    ConfigArgs {
        socket_path,
        host,
        port,
        token,
        mac,
    }
}

/// Single-instance + stale-socket handling: if the path exists and something is
/// actually listening, another instance owns it — exit. Otherwise remove the stale
/// socket and bind. (Mirrors the Python daemon's single-instance guard intent.)
fn bind(socket_path: &str) -> std::io::Result<UnixListener> {
    if std::path::Path::new(socket_path).exists() {
        if std::os::unix::net::UnixStream::connect(socket_path).is_ok() {
            eprintln!("divoomd: another instance already owns {socket_path}");
            std::process::exit(1);
        }
        let _ = std::fs::remove_file(socket_path);
    }
    UnixListener::bind(socket_path)
}

use divoomd::socket_server::{serve, serve_tcp, CONNECTION_IDLE_TIMEOUT, MAX_CONNECTIONS};

fn env_usize(key: &str, default: usize) -> usize {
    match std::env::var(key) {
        Ok(v) => v.parse().unwrap_or(default),
        Err(_) => default,
    }
}

fn env_duration(key: &str, default: Duration) -> Duration {
    match std::env::var(key) {
        Ok(v) => v.parse::<u64>().map(Duration::from_secs).unwrap_or(default),
        Err(_) => default,
    }
}

#[tokio::main]
async fn main() {
    // `divoomd mcp` runs the MCP stdio server (a client of the running daemon),
    // not the daemon itself. Ported from the Python `divoom_lib.cli mcp-server`.
    if std::env::args().nth(1).as_deref() == Some("mcp") {
        if let Err(e) = divoomd::mcp::run().await {
            eprintln!("divoomd mcp: {e}");
            std::process::exit(1);
        }
        return;
    }

    let args = parse_args();
    let socket_path = args.socket_path;
    let listener = match bind(&socket_path) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("divoomd: cannot bind {socket_path}: {e}");
            std::process::exit(1);
        }
    };
    eprintln!("divoomd listening on {socket_path}");

    let mut tcp_listener = None;
    let mut tcp_token = None;
    if let Some(host) = args.host {
        let port = match args.port {
            Some(p) => p,
            None => {
                eprintln!("divoomd: TCP port is required when host is specified");
                std::process::exit(1);
            }
        };
        let token = match args.token {
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
        tcp_listener = Some(l);
        tcp_token = Some(token);
    }

    let daemon = Arc::new(Daemon::new_with_mac(args.mac));
    daemon.initialize_self_weak(Arc::downgrade(&daemon));

    // Monthly-best background sync is OPT-IN (parity: in Python it is a SEPARATE
    // daemon, not the main one). Without this gate the main daemon would push
    // gallery animations to every configured device on each startup. Enable with
    // DIVOOMD_MONTHLY_BEST=1.
    if matches!(
        std::env::var("DIVOOMD_MONTHLY_BEST").as_deref(),
        Ok("1") | Ok("true") | Ok("yes")
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

    let unix_fut = serve(listener, daemon.clone(), max_connections, idle_timeout);

    let shutdown = daemon.shutdown.clone();
    if let (Some(l), Some(t)) = (tcp_listener, tcp_token) {
        let tcp_fut = serve_tcp(l, daemon.clone(), t, max_connections, idle_timeout);
        tokio::select! {
            _ = unix_fut => {}
            _ = tcp_fut => {}
            sig = shutdown_signal() => {
                eprintln!("divoomd: {sig} — shutting down");
            }
            _ = shutdown.notified() => {
                eprintln!("divoomd: shutdown command — shutting down");
                // brief grace so the command's reply flushes to the client
                tokio::time::sleep(std::time::Duration::from_millis(150)).await;
            }
        }
    } else {
        tokio::select! {
            _ = unix_fut => {}
            sig = shutdown_signal() => {
                eprintln!("divoomd: {sig} — shutting down");
            }
            _ = shutdown.notified() => {
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
    let _ = std::fs::remove_file(&socket_path);
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
