//! Positional-argument extraction for `device_call`.
//!
//! Split out of `mod.rs` in R67 when that file crossed the house 500-line cap.
//! See the warning on `args` in `mod.rs`: the numeric list is COMPACTED, so
//! only these helpers give true positional reads.

use serde_json::Value;

/// Read a positional integer argument by its TRUE index, falling back to a
/// keyword of the same name.
///
/// R67/C7: handlers used to index the compacted numeric `args` list, whose
/// indices only match the call signature when every earlier argument is also a
/// number. A leading string (a colour, a path, a text body) shifts everything
/// after it, so the handler reads a neighbouring argument's value with total
/// confidence. `raw_args` preserves real positions; this reads from there.
pub(crate) fn pos_i64(
    raw_args: &[Value],
    idx: usize,
    kw: Option<&serde_json::Map<String, Value>>,
    name: &str,
    default: i64,
) -> i64 {
    raw_args
        .get(idx)
        .and_then(|v| v.as_i64())
        .or_else(|| kw.and_then(|m| m.get(name)).and_then(|v| v.as_i64()))
        .unwrap_or(default)
}

/// Positional boolean argument by true index, falling back to a keyword.
pub(crate) fn pos_bool(
    raw_args: &[Value],
    idx: usize,
    kw: Option<&serde_json::Map<String, Value>>,
    name: &str,
    default: bool,
) -> bool {
    let as_flag = |v: &Value| -> Option<bool> {
        // Accept 1/0 as well as true/false: Python treats them
        // interchangeably at these call sites, and a caller passing 1 must not
        // silently mean false.
        v.as_bool().or_else(|| v.as_i64().map(|n| n != 0))
    };
    raw_args
        .get(idx)
        .and_then(as_flag)
        .or_else(|| kw.and_then(|m| m.get(name)).and_then(as_flag))
        .unwrap_or(default)
}
