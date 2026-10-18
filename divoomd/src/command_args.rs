//! What each daemon command must be given, stated once (P5.9).
//!
//! Every handler used to pull its own arguments and refuse a missing one in
//! its own words -- `err_reply("live_job_start requires 'mac'")`, 27 times
//! -- with no `code`, so a program could not tell a malformed request from a
//! device failure without matching prose. One handler (`custom_art_push`)
//! even stopped the panel's live job before noticing it had nothing to push.
//!
//! [`COMMAND_ARGS`] names every command the dispatcher answers and what it
//! requires. The dispatcher checks it before any handler runs, so a request
//! missing an argument is refused with `bad_request` and has no effect; a
//! handler's own later check (an empty string, a one-of the table cannot
//! say) refuses through [`missing`], which carries the same code.
//! `command_args_tests` holds the table to the dispatcher's arms both ways,
//! so a new command cannot skip it.

use serde_json::Value;

use crate::protocol::{err_code, ErrorCode};

/// The JSON type a required argument must have.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ArgType {
    Str,
    Int,
    Bool,
    Object,
    Array,
    /// Present and not null; the handler reads any shape.
    Any,
}

impl ArgType {
    fn admits(self, v: &Value) -> bool {
        match self {
            Self::Str => v.is_string(),
            Self::Int => v.is_i64() || v.is_u64(),
            Self::Bool => v.is_boolean(),
            Self::Object => v.is_object(),
            Self::Array => v.is_array(),
            Self::Any => !v.is_null(),
        }
    }

    const fn noun(self) -> &'static str {
        match self {
            Self::Str => "a string",
            Self::Int => "an integer",
            Self::Bool => "a boolean",
            Self::Object => "an object",
            Self::Array => "an array",
            Self::Any => "a value",
        }
    }
}

/// One requirement: at least one of these keys, with its type.
pub type Required = &'static [(&'static str, ArgType)];

use ArgType::{Any, Array, Bool, Int, Object, Str};

/// Every command the dispatcher answers, and what it cannot run without.
pub const COMMAND_ARGS: &[(&str, &[Required])] = &[
    ("ping", &[]),
    ("get_status", &[]),
    ("device_status", &[]),
    ("exclusive_start", &[&[("token", Str)]]),
    ("exclusive_end", &[&[("token", Str)]]),
    ("lease_acquire", &[&[("ttl_ms", Int)]]),
    ("lease_renew", &[&[("token", Str)], &[("ttl_ms", Int)]]),
    ("lease_release", &[&[("token", Str)]]),
    ("shutdown", &[]),
    ("probe_lan", &[]),
    ("sync_artwork", &[&[("file_id", Str)]]),
    ("get_animated_preview", &[&[("file_id", Str)]]),
    ("scan", &[]),
    (
        "connect",
        &[&[("mac", Str), ("id", Str), ("lan_ip", Str), ("mock", Bool)]],
    ),
    ("select_device", &[&[("mac", Str)]]),
    ("disconnect", &[]),
    ("mock_simulate_drop", &[]),
    ("device_call", &[&[("method", Str)]]),
    ("live_job_start", &[&[("mac", Str)], &[("kind", Str)]]),
    ("live_job_stop", &[&[("mac", Str)], &[("kind", Str)]]),
    ("live_job_list", &[]),
    ("live_jobs_stop_for", &[]),
    ("set_device_activity", &[&[("mac", Str)], &[("kind", Str)]]),
    ("get_device_activity", &[]),
    ("owned_devices", &[]),
    (
        "custom_art_push",
        &[&[("slots", Object), ("file_ids", Array)]],
    ),
    ("custom_art_query_page", &[]),
    ("hot_update", &[]),
    ("hot_update_progress", &[]),
    ("hot_manifest", &[]),
    ("now_playing", &[]),
    ("players", &[]),
    ("weather", &[]),
    ("render_widget", &[&[("kind", Str)]]),
    ("sysmon", &[]),
    ("wall_configure", &[]),
    ("get_topology", &[]),
    ("set_topology", &[]),
    ("start_notifications", &[]),
    ("stop_notifications", &[]),
    ("notification_status", &[]),
    ("set_routing", &[&[("rules", Any)]]),
    ("fetch_gallery", &[&[("classify", Int)]]),
    ("save_credentials", &[&[("email", Str)]]),
    ("get_credentials", &[]),
    ("get_cached_credentials", &[]),
    ("get_category_file_list", &[]),
    ("get_dial_types", &[]),
    ("store_clock_faces", &[]),
    ("get_dial_list", &[&[("dial_type", Str)]]),
    ("list_clock_faces", &[]),
    ("search_weather_city", &[]),
    ("get_aid_sleep_list", &[&[("sleep_type", Int)]]),
    ("get_my_aid_sleep_list", &[&[("sleep_type", Int)]]),
    ("get_my_playlists", &[]),
    ("get_playlist_images", &[&[("play_id", Int)]]),
    ("get_photo_albums", &[]),
];

/// `'a'`, `'a' or 'b'`, `'a', 'b' or 'c'`.
fn keys(req: Required) -> String {
    let quoted: Vec<String> = req.iter().map(|(k, _)| format!("'{k}'")).collect();
    match quoted.split_last() {
        Some((last, rest)) if !rest.is_empty() => format!("{} or {last}", rest.join(", ")),
        _ => quoted.concat(),
    }
}

/// The refusal for a request missing what it needs: `bad_request`, naming
/// the command and the argument.
#[must_use]
pub fn missing(command: &str, what: &str) -> Value {
    err_code(ErrorCode::BadRequest, &format!("{command} requires {what}"))
}

/// Refuse `args` when `command` requires something they lack (absent, null,
/// or of the wrong type). A command not in the table requires nothing here;
/// the dispatcher answers it `unknown_command`.
///
/// # Errors
///
/// The `bad_request` reply naming the command and what is missing.
pub fn check(command: &str, args: &Value) -> Result<(), Value> {
    let Some((_, required)) = COMMAND_ARGS.iter().find(|(c, _)| *c == command) else {
        return Ok(());
    };
    for req in *required {
        let present: Vec<(&str, ArgType, &Value)> = req
            .iter()
            .filter_map(|(k, t)| args.get(*k).filter(|v| !v.is_null()).map(|v| (*k, *t, v)))
            .collect();
        if present.is_empty() {
            return Err(missing(command, &keys(req)));
        }
        if let Some((k, t, _)) = present.iter().find(|(_, t, v)| !t.admits(v)) {
            return Err(missing(command, &format!("'{k}' to be {}", t.noun())));
        }
    }
    Ok(())
}
