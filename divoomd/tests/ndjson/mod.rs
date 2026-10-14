//! Line framing for the socket-server tests: one NDJSON line per call.
//!
//! A single `read` is neither one message nor a whole one. A 64 KB reply comes
//! back TRUNCATED from a fixed buffer, and under load two small events come back
//! in ONE chunk -- at load ~140 a read-then-parse died on "trailing characters"
//! and reported on the test's own framing rather than on the server. This reads
//! a byte at a time up to the newline, so it never consumes a byte of the NEXT
//! line: a caller can interleave writes and reads on one stream with no buffer
//! to carry between calls.

use std::time::Duration;

use serde_json::Value;
use tokio::io::AsyncReadExt;
use tokio::net::UnixStream;

/// The next whole line on `stream` as JSON; `None` when EOF, a read error or
/// the deadline comes first ("no line is coming"). A line that is not JSON
/// panics with the line: that is a server defect, not "nothing yet".
pub async fn next_line(stream: &mut UnixStream, limit: Duration) -> Option<Value> {
    let deadline = tokio::time::Instant::now() + limit;
    let mut line = Vec::new();
    loop {
        let left = deadline.checked_duration_since(tokio::time::Instant::now())?;
        match tokio::time::timeout(left, stream.read_u8()).await {
            Ok(Ok(b'\n')) => break,
            Ok(Ok(b)) => line.push(b),
            _ => return None,
        }
    }
    Some(serde_json::from_slice(&line).unwrap_or_else(|e| {
        panic!(
            "not one JSON line ({e}): {}",
            String::from_utf8_lossy(&line)
        )
    }))
}
