//! Taking the Unix socket: race-free, self-healing, and never silently fatal.
//!
//! # What this replaces
//!
//! The old `bind()` was three lines of check-then-act:
//!
//! ```ignore
//! if path.exists() {
//!     if UnixStream::connect(path).is_ok() { exit(1) }   // someone is live
//!     let _ = remove_file(path);                          // else assume stale
//! }
//! UnixListener::bind(path)
//! ```
//!
//! It handled the ordinary stale socket and nothing else, and it failed in ways
//! the user could not act on:
//!
//! * **Every other blocker collapsed into one opaque errno.** A directory or a
//!   regular file sitting on the path, a missing parent directory, a socket
//!   owned by another user, a path over the `sun_path` limit — all of them came
//!   out as `cannot bind /tmp/divoom.sock: Address already in use` or
//!   `Invalid argument`. Nothing said which one, and none of them are fixed the
//!   same way.
//! * **`sun_path` is ~104 bytes on macOS.** A long path fails with `Invalid
//!   argument` — an error that reads like a bug in the daemon rather than a
//!   limit in the kernel.
//! * **The check and the bind were not atomic.** Two daemons starting together
//!   both saw "nothing listening", both unlinked, and both bound. The loser's
//!   listener stayed open on an unlinked inode: reachable by nobody, invisible
//!   to every UI, still holding the single-owner `CoreBluetooth` central. That is
//!   the 34-hour orphan described in [`crate::socket_owner`], and it is created
//!   *here*, at startup — the ownership check only limits the damage at exit.
//! * **The user never saw the reason.** The daemon is spawned detached by the
//!   GUI with stderr redirected to a log file, so `eprintln!` then `exit(1)`
//!   means the GUI reports "no daemon" and the explanation sits in a file
//!   nobody opens.
//!
//! # How this one works
//!
//! An advisory lock on a sidecar `<socket>.lock` makes inspect-and-bind ATOMIC
//! across processes. Every decision below happens while holding it, so the
//! "both daemons saw an empty path" race cannot occur: the second daemon either
//! waits behind the lock or is told a startup is already in progress. The lock
//! is held for the process lifetime, not just during bind.
//!
//! Blockers are then distinguished and each gets its own remedy
//! ([`BindFailure::remedy`]). Self-healing is limited to the two cases that are
//! unambiguously safe — a stale socket nothing is listening on, and a missing
//! parent directory. A path occupied by a *regular file* is never removed: that
//! is someone's data, and guessing wrong is unrecoverable.
//!
//! Whatever happens, the reason is written to `<socket>.failure` as well as
//! stderr, so the client can surface it (see `divoom_client.socket_failure`).

use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::time::Duration;

use crate::socket_owner::{HeldSocket, SocketOwnership};

// Re-exported so `socket_bind::BindFailure` keeps resolving for every caller
// and test; the type simply lives in its own file now.
pub use crate::bind_failure::BindFailure;

/// Longest usable `sockaddr_un.sun_path`, minus the NUL terminator.
///
/// macOS is 104 and Linux 108. Checked up front because the kernel's own
/// complaint for an over-long path is `EINVAL` / "Invalid argument", which
/// points at the code rather than at the path.
#[cfg(target_os = "macos")]
pub const MAX_SOCKET_PATH: usize = 103;
#[cfg(not(target_os = "macos"))]
pub const MAX_SOCKET_PATH: usize = 107;

/// How long to wait for a listener to identify itself as divoomd.
const PROBE_TIMEOUT: Duration = Duration::from_millis(750);

/// A freshly bound socket, before it is handed to a runtime.
///
/// Short-lived by design: [`Acquired::into_held`] converts it into a
/// [`HeldSocket`], which is what actually governs the socket's lifetime.
#[derive(Debug)]
pub struct Acquired {
    path: String,
    listener: UnixListener,
    lock: StartupLock,
    /// Captured under the startup lock, microseconds after `bind`, so there is
    /// no window in which the path could be replaced between binding it and
    /// recording what we bound. Reading it later — as `main` used to, with its
    /// own `SocketOwnership::of` call after the lock section — is a second
    /// check-then-act, and check-then-act on this path is the entire bug class
    /// [`crate::socket_owner`] exists to close.
    owned: Option<SocketOwnership>,
}

/// The held startup lock.
///
/// Its only job is to stay alive: dropping it releases the advisory lock and
/// lets a second daemon race us. It is a distinct type so that `let _ = ...`
/// (which would drop it immediately) reads as obviously wrong at the call site.
/// The field is named `_file` rather than carrying an `#[allow(dead_code)]`:
/// nothing reads it, and that is the point, so the underscore states the intent
/// where a lint suppression would only have hidden the question.
#[derive(Debug)]
pub struct StartupLock {
    _file: std::fs::File,
}

impl StartupLock {
    /// Wrap an already-`flock`ed file as the held lock.
    ///
    /// Crate-visible rather than private so [`crate::socket_owner`]'s tests can
    /// build a `HeldSocket` without going through a real `acquire`; taking the
    /// lock is `acquire`'s job and stays here.
    pub(crate) const fn hold(file: std::fs::File) -> Self {
        Self { _file: file }
    }
}

impl Acquired {
    /// Hand the socket to a runtime and take responsibility for releasing it.
    ///
    /// `wrap` adapts the blocking `std` listener to whatever the caller's async
    /// runtime wants. It happens INSIDE this call so the lock, the listener and
    /// the recorded identity are never three loose values a caller could drop,
    /// reorder or forget one of.
    ///
    /// # Errors
    ///
    /// From the bind itself; see [`acquire`] for the cases.
    pub fn into_held<L>(
        self,
        wrap: impl FnOnce(UnixListener) -> std::io::Result<L>,
    ) -> std::io::Result<HeldSocket<L>> {
        let Self {
            path,
            listener,
            lock,
            owned,
        } = self;
        Ok(HeldSocket::new(path, wrap(listener)?, lock, owned))
    }
}

/// The path of the sidecar lock for a socket.
#[must_use]
pub fn lock_path(socket_path: &str) -> String {
    format!("{socket_path}.lock")
}

/// The path of the sidecar failure report for a socket.
#[must_use]
pub fn failure_path(socket_path: &str) -> String {
    format!("{socket_path}.failure")
}

/// What is currently at the path.
enum Occupant {
    Nothing,
    StaleSocket,
    LiveDivoomd,
    /// Accepted us and then SPOKE, but not as divoomd.
    Foreign,
    /// Accepted us and said nothing at all within `PROBE_TIMEOUT`.
    Unresponsive,
    NotASocket(&'static str),
    Denied(String),
}

/// Ask whatever is listening whether it is divoomd.
///
/// Identification matters: a stale socket is safe to delete, and a socket
/// belonging to another program is not. The old code never asked, so anything
/// that accepted a connection was assumed to be a healthy divoomd.
fn probe(path: &str) -> Occupant {
    let mut stream = match UnixStream::connect(path) {
        Ok(s) => s,
        Err(e) => {
            return match e.kind() {
                // Nobody is accepting: the file outlived its process.
                ErrorKind::PermissionDenied => Occupant::Denied(e.to_string()),
                ErrorKind::NotFound => Occupant::Nothing,
                _ => Occupant::StaleSocket,
            };
        }
    };
    let _ = stream.set_read_timeout(Some(PROBE_TIMEOUT));
    let _ = stream.write_all(b"{\"command\":\"get_status\"}\n");
    let _ = stream.flush();

    // divoomd pushes a `{"type":"status"}` event on connect and answers
    // get_status with a `daemon_version`. Either marker identifies it. Read a
    // few lines: the greeting may arrive before the reply.
    //
    // SILENCE IS ITS OWN ANSWER. Reporting "not divoomd" for a listener that
    // said NOTHING conflated two states with opposite remedies: a foreign
    // program (stop it, or move our socket) and a divoomd that has stopped
    // serving (stop THAT pid and restart). Observed 2026-09-07: a divoomd whose
    // 64 connection permits were all pinned by handlers that never returned had
    // stopped calling `accept()` entirely, so every connect completed into the
    // kernel backlog and got total silence -- and this probe told the user for
    // days that another program owned the path.
    let mut reader = BufReader::new(stream);
    let mut heard_anything = false;
    for _ in 0..4 {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) | Err(_) => break,
            Ok(_) => {
                heard_anything = true;
                if line.contains("daemon_version") || line.contains("\"type\":\"status\"") {
                    return Occupant::LiveDivoomd;
                }
            }
        }
    }
    if heard_anything {
        Occupant::Foreign
    } else {
        Occupant::Unresponsive
    }
}

/// Classify the path without touching it.
fn inspect(path: &str) -> Occupant {
    let md = match std::fs::symlink_metadata(path) {
        Ok(md) => md,
        Err(e) if e.kind() == ErrorKind::NotFound => return Occupant::Nothing,
        Err(e) if e.kind() == ErrorKind::PermissionDenied => {
            return Occupant::Denied(e.to_string())
        }
        Err(e) => return Occupant::Denied(e.to_string()),
    };
    let ft = md.file_type();
    if ft.is_dir() {
        return Occupant::NotASocket("directory");
    }
    if ft.is_file() {
        return Occupant::NotASocket("regular file");
    }
    if ft.is_symlink() {
        // Follow it: a symlink to our own socket is normal enough, but a
        // dangling one must not be reported as a live daemon.
        return match std::fs::metadata(path) {
            Ok(_) => probe(path),
            Err(_) => Occupant::StaleSocket,
        };
    }
    probe(path)
}

/// Take the exclusive startup lock, or report who has it.
fn take_lock(socket_path: &str) -> Result<std::fs::File, BindFailure> {
    let lp = lock_path(socket_path);
    let file = std::fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .truncate(false)
        .open(&lp)
        .map_err(|e| match e.kind() {
            ErrorKind::PermissionDenied => BindFailure::PermissionDenied { err: e.to_string() },
            _ => BindFailure::Io { err: e.to_string() },
        })?;
    // SAFETY: `file` owns the descriptor for the duration of the call.
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc != 0 {
        let err = std::io::Error::last_os_error();
        return match err.raw_os_error() {
            Some(libc::EWOULDBLOCK) => Err(BindFailure::StartupInProgress),
            _ => Err(BindFailure::Io {
                err: err.to_string(),
            }),
        };
    }
    Ok(file)
}

/// Make sure the parent directory exists, creating it when it does not.
fn ensure_parent(socket_path: &str) -> Result<(), BindFailure> {
    let Some(parent) = Path::new(socket_path).parent() else {
        return Ok(());
    };
    if parent.as_os_str().is_empty() || parent.is_dir() {
        return Ok(());
    }
    std::fs::create_dir_all(parent).map_err(|e| BindFailure::ParentMissing {
        parent: parent.to_string_lossy().into_owned(),
        err: e.to_string(),
    })
}

/// Acquire the socket, healing what is safe to heal.
///
/// Everything after the lock is taken is serialized against other divoomd
/// startups, so the inspect-then-bind sequence is atomic.
///
/// # Errors
///
/// When the socket path is too long for `sockaddr_un`, when another instance is
/// mid-startup, and when the path is held by a live incumbent. The variants are
/// distinct on purpose: a stale file is reclaimed, a live owner is not.
pub fn acquire(socket_path: &str) -> Result<Acquired, BindFailure> {
    let len = socket_path.len();
    if len > MAX_SOCKET_PATH {
        return Err(BindFailure::PathTooLong {
            len,
            max: MAX_SOCKET_PATH,
        });
    }
    ensure_parent(socket_path)?;

    // If the lock is held, say WHICH of the two situations it is. The lock is
    // kept for the daemon's whole life, not just its startup, so a plain
    // "startup in progress" would be the answer even when a daemon has been
    // serving for hours — technically true of the lock, useless to the reader.
    // Probe first and report the live instance when there is one.
    let lock = match take_lock(socket_path) {
        Ok(l) => l,
        Err(BindFailure::StartupInProgress) => {
            // Holding this lock file is something only divoomd does, so the
            // holder IS a divoomd and the only question is how far along it is.
            // Deliberately NOT reported as a foreign listener: `main` binds
            // early and serves after setup, so a socket that accepts but does
            // not yet answer is our own daemon mid-startup, and calling that
            // "in use by another program" would send the user hunting for a
            // program that does not exist.
            return Err(match inspect(socket_path) {
                Occupant::LiveDivoomd => BindFailure::LiveInstance,
                _ => BindFailure::StartupInProgress,
            });
        }
        Err(e) => return Err(e),
    };

    match inspect(socket_path) {
        Occupant::LiveDivoomd => return Err(BindFailure::LiveInstance),
        Occupant::Foreign => return Err(BindFailure::ForeignListener),
        // Same reasoning as the StartupInProgress arm above, which already
        // refused to call a silent-but-listening socket "another program": a
        // listener that accepts and says nothing is far more likely to be our
        // own daemon than a stranger's. That arm covered the mid-startup case
        // and stopped there; this one covers the wedged-after-hours case, which
        // is what actually reached a user (2026-09-07, a divoomd deaf for five
        // days because all 64 connection permits were pinned).
        Occupant::Unresponsive => return Err(BindFailure::UnresponsiveListener),
        Occupant::NotASocket(kind) => return Err(BindFailure::NotASocket { kind }),
        Occupant::Denied(err) => return Err(BindFailure::PermissionDenied { err }),
        Occupant::StaleSocket => {
            // The one case that is unambiguously safe to clear: a socket file
            // whose process is gone. Under the lock, so nothing can bind it
            // between this unlink and ours.
            if let Err(e) = std::fs::remove_file(socket_path) {
                if e.kind() != ErrorKind::NotFound {
                    return Err(match e.kind() {
                        ErrorKind::PermissionDenied => {
                            BindFailure::PermissionDenied { err: e.to_string() }
                        }
                        _ => BindFailure::Io { err: e.to_string() },
                    });
                }
            }
        }
        Occupant::Nothing => {}
    }

    match UnixListener::bind(socket_path) {
        Ok(listener) => {
            clear_failure(socket_path);
            Ok(Acquired {
                path: socket_path.to_string(),
                listener,
                // Still under the advisory lock: no other divoomd can be
                // between its unlink and its bind while we read this.
                owned: SocketOwnership::of(socket_path),
                lock: StartupLock::hold(lock),
            })
        }
        Err(e) => Err(match e.kind() {
            ErrorKind::PermissionDenied => BindFailure::PermissionDenied { err: e.to_string() },
            _ => BindFailure::Io { err: e.to_string() },
        }),
    }
}

/// Write the reason somewhere the client can read it.
///
/// The daemon is spawned detached with stderr going to a log file, so stderr
/// alone means the GUI can only say "no daemon". This file is the machine
/// -readable half: one `key: value` line each, easy to surface verbatim.
pub fn write_failure(socket_path: &str, failure: &BindFailure) {
    let body = format!(
        "reason: {}\nremedy: {}\ntransient: {}\n",
        failure.reason(socket_path),
        failure.remedy(),
        failure.is_transient(),
    );
    let _ = std::fs::write(failure_path(socket_path), body);
}

/// Drop a stale failure report once we are up, so it cannot mislead later.
pub fn clear_failure(socket_path: &str) {
    let _ = std::fs::remove_file(failure_path(socket_path));
}

#[cfg(test)]
#[path = "socket_bind_tests.rs"]
mod tests;
