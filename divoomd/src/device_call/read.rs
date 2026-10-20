//! One read, one answer -- and a read that gets NO answer is a failure.
//!
//! Before P2.8 every read in this layer ended the same way: a panel that
//! said nothing produced `{"success": true, "result": null}`. That is a
//! failure dressed as a success: the client could not tell "the panel has no
//! such value" from "the panel is gone", and a dropped link read as a
//! successful call with a null result.
//!
//! So the read has ONE exit, and it is typed by what actually happened:
//!
//! * the panel answered, with enough bytes to read the value -> the value;
//! * the panel answered with too few bytes -> a failure that says so
//!   (`device_failed`: the answer was there and unusable);
//! * the panel did not answer at all -> a failure (`device_failed`: the panel
//!   is quiet -- the link may still be up);
//! * the link failed -- the command could not be sent -> a failure
//!   (`device_disconnected`), which is the one class the daemon acts on: the
//!   panel is not there any more, so the link is retired and the drop is
//!   reported.
//!
//! The code, not the prose, is the contract: `device_disconnected` is what
//! tells the daemon a link is gone (see `crate::daemon::cmd_device_call`).

use std::time::Duration;

use serde_json::Value;

use crate::protocol::{err_code, ErrorCode};
use crate::transport::{DeviceTransport, Read};

/// Read one value from the panel, or say why there is none.
///
/// `what` names the method the client called (`get_brightness`), `cmd_id` the
/// opcode the panel was asked, and `min_len` the shortest answer the value can
/// be read from. `parse` turns the answer into the reply when there is one.
pub async fn read_reply<F>(
    dev: &DeviceTransport,
    what: &str,
    cmd_id: u8,
    args: &[u8],
    timeout: Duration,
    min_len: usize,
    parse: F,
) -> Value
where
    F: FnOnce(&[u8]) -> Value,
{
    match dev.send_command_and_wait(cmd_id, args, timeout).await {
        Read::Answered(p) if p.len() >= min_len => parse(&p),
        Read::Answered(p) => err_code(
            ErrorCode::DeviceFailed,
            &format!(
                "{what}: the panel's answer to 0x{cmd_id:02x} was {} bytes, expected {min_len}",
                p.len()
            ),
        ),
        Read::Silent => err_code(
            ErrorCode::DeviceFailed,
            &format!("{what}: the panel did not answer 0x{cmd_id:02x}"),
        ),
        Read::LinkFailed(why) => err_code(
            ErrorCode::DeviceDisconnected,
            &format!("{what}: the panel's link failed: {why}"),
        ),
    }
}
