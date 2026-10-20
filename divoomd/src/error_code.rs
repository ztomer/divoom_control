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
//!
//! This module is also the ONLY place a reply's `success` is written (P5.10):
//! [`ok_reply`] for a success, [`err_code`] / [`err_with`] for a failure, and
//! both failure constructors take an [`ErrorCode`]. The old code-less
//! `protocol::err_reply` is gone, `reply_shape_scan_tests` refuses a
//! hand-built `"success": false` anywhere else, and [`uncoded_failure`] is
//! checked on every reply the daemon sends ([`check_on_wire`]).

use serde_json::Value;

/// Every failure class a client may branch on.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorCode {
    /// The line was not JSON, or not an object with a `command` string.
    BadRequest,
    /// The daemon does not implement this command, or this `device_call`
    /// method.
    UnknownCommand,
    /// The panel named in the request is not connected -- or its link failed
    /// while the request ran: the command could not be sent, so the panel is
    /// not there any more (P2.8). The daemon acts on this code: the link is
    /// retired and the drop is reported.
    DeviceDisconnected,
    /// No panel is connected at all (for a wall call: no wall is configured).
    NoDevice,
    /// The panel named has never been linked to this daemon (or `disconnect`
    /// forgot it), so there is no link for state about it to wait for (P5.8).
    UnknownDevice,
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
    /// Not available here: on this platform, in this build, or over this
    /// panel's link (a LAN panel has no Bluetooth-only command). The
    /// platform case was the first; the build case was already on the wire
    /// (`connect` without BLE), and P5.10 named the link case.
    Unsupported,
    /// Another holder leases this panel's screen (P4.6); the reply says who
    /// and for how long.
    ScreenLeased,
    /// The lease token is not (or no longer) the panel's lease.
    LeaseExpired,
    /// The panel is there, and it did not do what was asked: it did not
    /// answer, or it answered with something the daemon could not read, or a
    /// wall panel did not take the command. The request itself was
    /// well-formed; retrying, or checking the panel, may help (P5.10).
    ///
    /// A command that could not be SENT is not this: that is
    /// [`Self::DeviceDisconnected`] (P2.8).
    DeviceFailed,
    /// The daemon is already doing this -- a scan, a connect, a hot update --
    /// or another session holds the panel exclusively; retry when it is done
    /// (P5.10).
    Busy,
    /// The request's token does not match the daemon's; resend with the
    /// right one (P5.10).
    Unauthorized,
    /// A network service the daemon calls on the client's behalf -- the
    /// Divoom cloud, a weather or quote provider -- failed or refused; the
    /// panel is not involved (P5.10).
    UpstreamFailed,
    /// Something inside the daemon or on its host failed: a file it could not
    /// write, a host service that errored, a daemon not fully started. Not the
    /// request's fault and not the panel's (P5.10).
    Internal,
}

impl ErrorCode {
    /// Every code, for exhaustive checks.
    pub const ALL: &[Self] = &[
        Self::BadRequest,
        Self::UnknownCommand,
        Self::DeviceDisconnected,
        Self::NoDevice,
        Self::UnknownDevice,
        Self::AmbiguousTarget,
        Self::DeadlineExceeded,
        Self::ResourceExhausted,
        Self::NotificationDbMissing,
        Self::NotificationDbUnreadable,
        Self::Unsupported,
        Self::ScreenLeased,
        Self::LeaseExpired,
        Self::DeviceFailed,
        Self::Busy,
        Self::Unauthorized,
        Self::UpstreamFailed,
        Self::Internal,
    ];

    /// The wire name.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BadRequest => "bad_request",
            Self::UnknownCommand => "unknown_command",
            Self::DeviceDisconnected => "device_disconnected",
            Self::NoDevice => "no_device",
            Self::UnknownDevice => "unknown_device",
            Self::AmbiguousTarget => "ambiguous_target",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::ResourceExhausted => "resource_exhausted",
            Self::NotificationDbMissing => "notification_db_missing",
            Self::NotificationDbUnreadable => "notification_db_unreadable",
            Self::Unsupported => "unsupported",
            Self::ScreenLeased => "screen_leased",
            Self::LeaseExpired => "lease_expired",
            Self::DeviceFailed => "device_failed",
            Self::Busy => "busy",
            Self::Unauthorized => "unauthorized",
            Self::UpstreamFailed => "upstream_failed",
            Self::Internal => "internal",
        }
    }
}

/// A successful reply `{"success": true, ...extra}`.
#[must_use]
pub fn ok_reply(extra: Value) -> Value {
    let mut map = match extra {
        Value::Object(m) => m,
        _ => serde_json::Map::new(),
    };
    map.insert("success".into(), Value::Bool(true));
    Value::Object(map)
}

/// An error reply with its code: `{"success": false, "error": msg, "code": ...}`.
#[must_use]
pub fn err_code(code: ErrorCode, msg: &str) -> Value {
    err_with(code, msg, Value::Null)
}

/// [`err_code`] plus the reply's own detail fields (`degraded`, `cause`,
/// `state`, ...). `success`, `error` and `code` are written last, so the
/// detail cannot overwrite them.
#[must_use]
pub fn err_with(code: ErrorCode, msg: &str, extra: Value) -> Value {
    let mut map = match extra {
        Value::Object(m) => m,
        _ => serde_json::Map::new(),
    };
    map.insert("success".into(), Value::Bool(false));
    map.insert("error".into(), Value::String(msg.to_string()));
    map.insert("code".into(), Value::String(code.as_str().to_string()));
    Value::Object(map)
}

/// Why `reply` breaks the failure contract, or `None` when it keeps it.
///
/// A break is a `success` that is not `true` with no known `code`, or with
/// no `error` prose. A line with no `success` at all (an event) is not a
/// reply and is not judged.
#[must_use]
pub fn uncoded_failure(reply: &Value) -> Option<&'static str> {
    let success = reply.get("success")?;
    if success == &Value::Bool(true) {
        return None;
    }
    let Some(code) = reply.get("code").and_then(Value::as_str) else {
        return Some("a failure reply with no code");
    };
    if !ErrorCode::ALL.iter().any(|c| c.as_str() == code) {
        return Some("a failure reply whose code is not an ErrorCode");
    }
    if !reply.get("error").is_some_and(Value::is_string) {
        return Some("a failure reply with no error prose");
    }
    None
}

/// The wire check: every reply the daemon sends passes through here.
///
/// A failure without a code is a daemon defect: it fails any debug build (so
/// every test that provokes it goes red) and is logged in a release one,
/// where the reply still goes out rather than the request being dropped.
pub fn check_on_wire(reply: &Value) {
    let why = uncoded_failure(reply);
    debug_assert!(why.is_none(), "{why:?} on the wire: {reply}");
    if let Some(why) = why {
        eprintln!("[Err] {why} on the wire: {reply}");
    }
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

/// A failure as a CLIENT of the daemon sees it -- the MCP tools and the CLI
/// verbs: the prose, and the daemon's `code` when the daemon gave one.
///
/// Every tool error used to be a `String`, so `mcp_daemon::check` read the
/// reply's `error` and dropped its `code`: an agent told "no panel 'X' has
/// been linked" could not tell that from "panel busy" without matching words,
/// the class P3.2 ended at the socket and this ends one hop further out
/// (P5.8). The code is kept as its wire name rather than an [`ErrorCode`]: a
/// remote daemon newer than this client may send one this build does not
/// know, and dropping it would be the same loss again.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ToolError {
    pub message: String,
    pub code: Option<String>,
}

impl ToolError {
    /// The failure a daemon reply carries; `fallback` when it has no prose.
    #[must_use]
    pub fn from_reply(reply: &Value, fallback: &str) -> Self {
        Self {
            message: reply
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or(fallback)
                .to_string(),
            code: reply
                .get("code")
                .and_then(Value::as_str)
                .map(str::to_string),
        }
    }

    /// The line a CLI verb prints: the prose, then the code in brackets so a
    /// script can match the class rather than the wording. A method, not a
    /// `From<ToolError> for String`: that impl would let `?` flatten a tool
    /// error back into a `String` anywhere in the MCP chain, silently, which
    /// is the loss this type exists to end.
    #[must_use]
    pub fn cli_line(&self) -> String {
        self.code.as_ref().map_or_else(
            || self.message.clone(),
            |c| format!("{} [{c}]", self.message),
        )
    }

    /// `{"error": prose, "code": wire name}` -- `code` only when there is one.
    #[must_use]
    pub fn to_json(&self) -> Value {
        let mut v = serde_json::json!({ "error": self.message });
        if let Some(c) = &self.code {
            v["code"] = Value::String(c.clone());
        }
        v
    }
}

impl std::fmt::Display for ToolError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ToolError {}

impl From<String> for ToolError {
    fn from(message: String) -> Self {
        Self {
            message,
            code: None,
        }
    }
}

impl From<&str> for ToolError {
    fn from(message: &str) -> Self {
        message.to_string().into()
    }
}
