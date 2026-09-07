//! Why a socket could not be taken, and what the user should do about it.
//!
//! Split out of [`crate::socket_bind`] when that file hit the 500-line cap. The
//! seam is real rather than arbitrary: everything here is REPORTING — the
//! taxonomy of blockers, the sentence each one shows a user, its remedy, and its
//! exit code. Nothing here touches the filesystem or the socket. The mechanism
//! that decides which variant applies (locking, inspecting, probing, binding)
//! stays in `socket_bind`, which re-exports this type so every existing
//! `socket_bind::BindFailure` path keeps working.
//!
//! The distinction these variants exist to preserve is that two blockers can
//! look identical from outside and need opposite responses: a listener that
//! ANSWERS with a foreign protocol is someone else's program (leave it alone,
//! move our socket), while one that accepts and says NOTHING is almost always
//! our own daemon, wedged (stop that pid). Collapsing them told a user for five
//! days that another program owned /tmp/divoom.sock.

/// Why the socket could not be taken.
#[derive(Debug)]
pub enum BindFailure {
    /// A healthy divoomd already owns the path. Not an error condition so much
    /// as the single-instance guard doing its job.
    LiveInstance,
    /// Something is listening and SPOKE, but not divoomd's protocol. Removing it
    /// would break whatever program it belongs to, so we refuse instead.
    ForeignListener,
    /// Something is listening, accepted the connection, and said nothing at all.
    /// Overwhelmingly a divoomd that has stopped serving -- a healthy foreign
    /// daemon normally greets or errors. Kept distinct from `ForeignListener`
    /// because the remedies are opposite: stop OUR wedged pid, versus leave
    /// someone else's program alone and move our socket.
    UnresponsiveListener,
    /// A regular file or directory occupies the path. Never auto-removed.
    NotASocket { kind: &'static str },
    /// Another divoomd holds the startup lock right now.
    StartupInProgress,
    /// The parent directory is missing and could not be created.
    ParentMissing { parent: String, err: String },
    /// The path (or its lock) is not ours to touch.
    PermissionDenied { err: String },
    /// Longer than the platform's `sun_path`.
    PathTooLong { len: usize, max: usize },
    /// Anything else, kept verbatim rather than guessed at.
    Io { err: String },
}

impl BindFailure {
    /// One line saying what is wrong.
    pub fn reason(&self, path: &str) -> String {
        match self {
            Self::LiveInstance => format!("another divoomd is already listening on {path}"),
            Self::ForeignListener => format!(
                "{path} is in use by another program (it is listening and answers, \
                 but not as divoomd)"
            ),
            Self::UnresponsiveListener => format!(
                "{path} has a listener that accepted the connection and then sent \
                 nothing at all. That is what a WEDGED divoomd looks like, not what \
                 another program looks like"
            ),
            Self::NotASocket { kind } => {
                format!("{path} is a {kind}, not a socket")
            }
            Self::StartupInProgress => {
                format!("another divoomd is starting up and holds the lock for {path}")
            }
            Self::ParentMissing { parent, err } => {
                format!("the directory {parent} does not exist and could not be created: {err}")
            }
            Self::PermissionDenied { err } => {
                format!("permission denied for {path}: {err}")
            }
            Self::PathTooLong { len, max } => {
                format!("the socket path is {len} characters; this platform allows {max}")
            }
            Self::Io { err } => format!("cannot bind {path}: {err}"),
        }
    }

    /// What the user should actually do about it.
    pub fn remedy(&self) -> &'static str {
        match self {
            Self::LiveInstance => {
                "Nothing to do — the running daemon is healthy. Stop it first if you \
                 meant to replace it."
            }
            Self::ForeignListener => {
                "Point divoomd at a different socket with --socket, or stop the other \
                 program. Use `lsof` on the path to see who owns it."
            }
            Self::UnresponsiveListener => {
                "Run `lsof <socket>` to see who holds it. If it is a divoomd, it has \
                 stopped answering: kill that pid and start again. The socket is not \
                 removed automatically because a listener still owns it."
            }
            Self::NotASocket { .. } => {
                "Move or delete that file yourself, then start the daemon again. It is \
                 not removed automatically because it may be data you care about."
            }
            Self::StartupInProgress => {
                "Wait a moment and try again; if it persists, no daemon is actually \
                 starting and the lock file can be deleted."
            }
            Self::ParentMissing { .. } => {
                "Create the directory (or choose an existing one with --socket)."
            }
            Self::PermissionDenied { .. } => {
                "The socket belongs to another user. Delete it as that user, or pass \
                 --socket with a path you own."
            }
            Self::PathTooLong { .. } => {
                "Choose a shorter --socket path; Unix sockets are limited by the \
                 kernel, not by divoomd."
            }
            Self::Io { .. } => "Check the path and permissions, then try again.",
        }
        .trim_ascii()
    }

    /// True when a second attempt could plausibly succeed on its own.
    pub fn is_transient(&self) -> bool {
        matches!(self, Self::StartupInProgress)
    }

    /// Does this failure describe the SOCKET's state, or only this process's?
    ///
    /// The sidecar exists to answer one client question: "why can I not reach a
    /// daemon?" Most failures answer it — nothing is listening, a file is in the
    /// way, permissions are wrong. `LiveInstance` answers the opposite: a
    /// healthy daemon owns the path and the caller simply lost the
    /// single-instance race. Writing that to the shared file made it report
    /// "another divoomd is already listening ... Nothing to do — the running
    /// daemon is healthy" as the reason a client was seeing an error, which is
    /// the loser's outcome dressed up as a fact about the socket.
    ///
    /// Found on 2026-08-30: a healthy daemon was serving `/tmp/divoom.sock`
    /// while `/tmp/divoom.sock.failure` still described a bind attempt that had
    /// lost to it. The variant's own doc comment already said it is "not an
    /// error condition so much as the single-instance guard doing its job" —
    /// the code just filed it as one anyway.
    pub fn describes_the_socket(&self) -> bool {
        !matches!(self, Self::LiveInstance)
    }

    /// Exit code. Distinct so a supervisor can tell "already running" (a benign
    /// no-op) from a real configuration problem without parsing text.
    pub fn exit_code(&self) -> i32 {
        match self {
            Self::LiveInstance => 3,
            Self::StartupInProgress => 4,
            _ => 1,
        }
    }
}
