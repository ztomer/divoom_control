//! Stable, machine-readable failure classes for replies (P3.2).
//!
//! A reply's `error` is prose for a person; its `code` is the contract for a
//! program. Before this, `err_reply` carried only the prose, so any client
//! that needed to act on a failure had to match wording -- and wording drifts:
//! the Settings card still looked for the Python daemon's `PermissionError`
//! text two releases after the Rust daemon stopped producing it, so its Full
//! Disk Access prompt could never fire. `crate::ble_fault` ended the same
//! class inside the daemon; this ends it at the protocol boundary.
//!
//! Wire names are lowercase `snake_case`, matching the two codes that were
//! already on the wire before this enum (`resource_exhausted`,
//! `deadline_exceeded`). A wire name, once shipped, never changes meaning.

use serde_json::Value;

/// Every failure class a client may branch on.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorCode {
    /// The line was not JSON, or not an object with a `command` string.
    BadRequest,
    /// The daemon does not implement this command.
    UnknownCommand,
    /// The panel named in the request is not connected.
    DeviceDisconnected,
    /// No panel is connected at all.
    NoDevice,
    /// Several panels are connected, none is active, and the request did not
    /// say which: pass `mac`.
    AmbiguousTarget,
    /// The command outran its per-command budget (`crate::deadlines`).
    DeadlineExceeded,
    /// The daemon is at its connection cap; retry with jitter.
    ResourceExhausted,
    /// The macOS Notification Center database was not found.
    NotificationDbMissing,
    /// The database exists but cannot be opened or read -- on macOS, the
    /// daemon lacks Full Disk Access.
    NotificationDbUnreadable,
    /// The feature does not exist on this platform.
    Unsupported,
    /// Another holder leases this panel's screen (P4.6); the reply says who
    /// and for how long.
    ScreenLeased,
    /// The lease token is not (or no longer) the panel's lease.
    LeaseExpired,
}

impl ErrorCode {
    /// Every code, for exhaustive checks.
    pub const ALL: &[Self] = &[
        Self::BadRequest,
        Self::UnknownCommand,
        Self::DeviceDisconnected,
        Self::NoDevice,
        Self::AmbiguousTarget,
        Self::DeadlineExceeded,
        Self::ResourceExhausted,
        Self::NotificationDbMissing,
        Self::NotificationDbUnreadable,
        Self::Unsupported,
        Self::ScreenLeased,
        Self::LeaseExpired,
    ];

    /// The wire name.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BadRequest => "bad_request",
            Self::UnknownCommand => "unknown_command",
            Self::DeviceDisconnected => "device_disconnected",
            Self::NoDevice => "no_device",
            Self::AmbiguousTarget => "ambiguous_target",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::ResourceExhausted => "resource_exhausted",
            Self::NotificationDbMissing => "notification_db_missing",
            Self::NotificationDbUnreadable => "notification_db_unreadable",
            Self::Unsupported => "unsupported",
            Self::ScreenLeased => "screen_leased",
            Self::LeaseExpired => "lease_expired",
        }
    }
}

/// An error reply with its code: `{"success": false, "error": msg, "code": ...}`.
#[must_use]
pub fn err_code(code: ErrorCode, msg: &str) -> Value {
    let mut reply = crate::protocol::err_reply(msg);
    if let Some(obj) = reply.as_object_mut() {
        obj.insert("code".into(), Value::String(code.as_str().to_string()));
    }
    reply
}

/// A failure with its class, for code that returns errors up a call chain
/// before they become a reply.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CodedError {
    pub code: ErrorCode,
    pub message: String,
}

impl CodedError {
    #[must_use]
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// The reply this failure becomes.
    #[must_use]
    pub fn reply(&self) -> Value {
        err_code(self.code, &self.message)
    }
}

impl std::fmt::Display for CodedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CodedError {}

impl From<CodedError> for String {
    fn from(e: CodedError) -> Self {
        e.message
    }
}
