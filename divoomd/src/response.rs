//! Notify/response correlation — the layer above framing that matches a device
//! reply to a sent command. Ported from `divoom_lib/ble_notify.py`
//! (`BleNotifyMixin`): the inbound-frame routing decision and the
//! `wait_for_response` / `wait_for_any_response` semantics.
//!
//! Two subtleties here are load-bearing and were the subject of this session's
//! hardware fixes, so they're pinned by tests:
//!   * the generic-ACK (0x33) rule and clearing the expected-response scalar —
//!     getting this wrong mis-detected the protocol autoprobe (the iOS-LE revert);
//!   * the listen-set taking priority and NOT clearing the scalar — what lets the
//!     0x8B animation retransmit frames queue without consuming the scalar.

use std::time::{Duration, Instant};

use tokio::sync::mpsc;

use crate::models::{GENERIC_ACK_COMMANDS, GENERIC_ACK_COMMAND_ID};

/// One parsed inbound frame (command id + data), regardless of framing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    pub command_id: u8,
    pub payload: Vec<u8>,
}

/// What the notification handler should do with an inbound frame, given the
/// currently-expected response command and the device-driven listen set.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HandlerAction {
    /// Queue the frame; leave the expected-response scalar untouched.
    Queue,
    /// Queue the frame AND clear the expected-response scalar.
    QueueAndClear,
    /// Drop the frame (nothing is waiting for it).
    Drop,
}

/// Decide how to route an inbound frame — mirrors `_handle_ios_le_notification` /
/// `_handle_basic_protocol_notification`'s shared decision:
///
///   * a command in the `listen` set is queued WITHOUT touching the scalar
///     (device-driven protocols, e.g. 0x8B animation retransmits) — checked first;
///   * the exact expected command, or a generic-ACK (0x33) when the expected
///     command is a generic-ACK command, is queued AND clears the scalar;
///   * anything else is dropped.
pub fn route_notification(cmd: u8, expected: Option<u8>, listen: &[u8]) -> HandlerAction {
    if listen.contains(&cmd) {
        return HandlerAction::Queue;
    }
    let is_expected = expected == Some(cmd);
    let is_generic_ack = expected.is_some()
        && cmd == GENERIC_ACK_COMMAND_ID
        && expected
            .map(|e| GENERIC_ACK_COMMANDS.contains(&e))
            .unwrap_or(false);
    if is_expected || is_generic_ack {
        HandlerAction::QueueAndClear
    } else {
        HandlerAction::Drop
    }
}

/// Wait for the response to `command_id`: resolve on the exact command id; treat a
/// generic-ACK (0x33, when `command_id` is a generic-ACK command) as an
/// intermediate ack and KEEP waiting; discard anything else; return `None` on
/// timeout or a closed channel. Mirrors `wait_for_response`.
pub async fn wait_for_response(
    rx: &mut mpsc::Receiver<Frame>,
    command_id: u8,
    timeout: Duration,
) -> Option<Vec<u8>> {
    let deadline = Instant::now() + timeout;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return None;
        }
        match tokio::time::timeout(remaining, rx.recv()).await {
            Err(_) => return None,   // overall timeout
            Ok(None) => return None, // channel closed
            Ok(Some(frame)) => {
                if frame.command_id == command_id {
                    return Some(frame.payload);
                }
                let is_generic_ack = frame.command_id == GENERIC_ACK_COMMAND_ID
                    && GENERIC_ACK_COMMANDS.contains(&command_id);
                // generic-ack -> keep waiting for the data frame; anything else -> discard.
                let _ = is_generic_ack;
                continue;
            }
        }
    }
}

/// Wait for the first frame whose command id is in `wanted` (device-driven
/// protocols where several different commands may arrive next, e.g. the hot-update
/// 0xF7/0x9E exchange). Returns `(command_id, payload)` or `None` on timeout.
/// Mirrors `wait_for_any_response`.
pub async fn wait_for_any_response(
    rx: &mut mpsc::Receiver<Frame>,
    wanted: &[u8],
    timeout: Duration,
) -> Option<(u8, Vec<u8>)> {
    let deadline = Instant::now() + timeout;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return None;
        }
        match tokio::time::timeout(remaining, rx.recv()).await {
            Err(_) => return None,
            Ok(None) => return None,
            Ok(Some(frame)) => {
                if wanted.contains(&frame.command_id) {
                    return Some((frame.command_id, frame.payload));
                }
                continue;
            }
        }
    }
}
