//! Device-command verbs for the `divoomd` binary.
//!
//! These are the CLI's device operations, moved out of Python. The CLI has been
//! a daemon client since 2026-09-12 — it opens no Bluetooth of its own — so
//! these verbs never had device logic in them; they had argument validation, a
//! capability lookup, and a `device_call` round trip. The first two are shared
//! with the MCP tools, the third is a socket request, and none of them needed a
//! Python runtime to work.
//!
//! **The four verbs here are the ones with no capability gate**, and that is a
//! deliberate subset, not an oversight. `set-radio`, `set-alarm` and
//! `set-temperature` refuse on panels that lack the feature, and the table that
//! knows which panels lack it (`divoom_lib/models/capabilities.py`, keyed by MAC
//! registry and device type) exists only in Python — the daemon has no
//! capability table. Porting those three means porting the table, and two
//! tables is a second thing to keep in sync, which is the class
//! `tools/check_weather_parity.py` was written for. Until that decision is made
//! on purpose, those verbs stay where the table is.
//!
//! Parsing is a pure function over a slice, like `cli_args::parse`, so every
//! argument error is testable without spawning a process.

use serde_json::{json, Value};

use crate::daemon_target::DaemonTarget;
use crate::mcp_daemon;

/// A device verb and the arguments it was given.
#[derive(Debug, PartialEq, Eq)]
pub enum Verb {
    SetVolume {
        value: i64,
    },
    SetBrightness {
        value: i64,
    },
    PushImage {
        path: String,
    },
    /// The same operation as [`Verb::PushImage`], under the name scripts use.
    PushGif {
        path: String,
    },
    SetRadio {
        freq_x10: i64,
    },
    /// `HH:MM` on a 24h clock, kept as written so the error can quote it back.
    SetAlarm {
        time: String,
        hour: i64,
        minute: i64,
    },
    SetTemperature {
        temperature: i64,
        weather: String,
    },
}

/// A parsed command line: the verb, plus the flags that apply to every verb.
#[derive(Debug, PartialEq, Eq)]
pub struct VerbRequest {
    pub verb: Verb,
    pub mac: Option<String>,
    pub json: bool,
}

/// What a verb produced: the sentence a human reads, and the structured value
/// `--json` prints. Both come from the same reply, so they cannot disagree.
#[derive(Debug, PartialEq, Eq)]
pub struct VerbOutcome {
    pub human: String,
    pub value: Value,
}

impl Verb {
    /// The name as it appears on the command line.
    #[must_use]
    pub const fn name(&self) -> &'static str {
        match self {
            Self::SetVolume { .. } => "set-volume",
            Self::SetBrightness { .. } => "set-brightness",
            Self::PushImage { .. } => "push-image",
            Self::PushGif { .. } => "push-gif",
            Self::SetRadio { .. } => "set-radio",
            Self::SetAlarm { .. } => "set-alarm",
            Self::SetTemperature { .. } => "set-temperature",
        }
    }
}

/// The verbs this binary answers, for `--help` and for the error that lists them.
///
/// One list: a verb that exists but is not named here cannot be found by someone
/// who typed it wrong, which is the only moment the list is read.
pub const VERB_NAMES: &[&str] = &[
    "set-volume",
    "set-brightness",
    "push-image",
    "push-gif",
    "set-radio",
    "set-alarm",
    "set-temperature",
];

/// Parse `args` as a verb invocation, or say that it is not one.
///
/// `None` means the first word is not a verb, and the caller should read the
/// arguments as daemon options. This is one function rather than an
/// `is_verb` predicate plus a parser because it is one decision: a predicate
/// that says yes hands the same string to a `match` that decides again, and
/// those two lists are exactly the kind of pair that drifts.
///
/// # Errors
///
/// A message naming what was wrong and what was expected — a missing or extra
/// value, a value of the wrong type, an unknown option. None of them fall back
/// to a default: a silently-defaulted argument is how `--sokcet` came to serve
/// the default socket in this binary's history.
#[must_use]
pub fn parse(args: &[String]) -> Option<Result<VerbRequest, String>> {
    let first = args.first()?;
    if !VERB_NAMES.contains(&first.as_str()) {
        return None;
    }
    let verb = first.as_str();
    let args = &args[1..];
    Some(parse_verb(verb, args))
}

/// The arguments of one invocation, split into the flags every verb takes and
/// the values it is about.
///
/// Its own type because the split is a real step with its own errors — a missing
/// `--mac` value, an unknown option — and folding it into each verb would put
/// the same loop in seven places.
struct Invocation<'a> {
    positional: Vec<&'a str>,
    mac: Option<String>,
    json: bool,
}

impl<'a> Invocation<'a> {
    /// # Errors
    ///
    /// `--mac` with no value, or a flag no verb has. A `-1` is a VALUE, not an
    /// option: `set-brightness -1` has to say "must be in [0..100]", not
    /// "unknown option", or the user cannot discover the bound from the mistake.
    fn collect(verb: &str, args: &'a [String]) -> Result<Self, String> {
        let mut positional: Vec<&str> = Vec::new();
        let mut mac: Option<String> = None;
        let mut json = false;
        let mut i = 0;
        while i < args.len() {
            let arg = args[i].as_str();
            if let Some(v) = arg.strip_prefix("--mac=") {
                mac = Some(v.to_string());
            } else if arg == "--mac" {
                mac = Some(
                    args.get(i + 1)
                        .cloned()
                        .ok_or_else(|| format!("{verb}: --mac requires a value"))?,
                );
                i += 1;
            } else if arg == "--json" {
                json = true;
            } else if arg.starts_with('-') && !is_negative_number(arg) {
                return Err(format!(
                    "{verb}: unknown option {arg:?}\n\nRun `divoomd --help` for usage."
                ));
            } else {
                positional.push(arg);
            }
            i += 1;
        }
        Ok(Self {
            positional,
            mac,
            json,
        })
    }
}

fn parse_verb(verb: &str, args: &[String]) -> Result<VerbRequest, String> {
    let Invocation {
        positional,
        mac,
        json: as_json,
    } = Invocation::collect(verb, args)?;

    let want = |n: usize| -> Result<(), String> {
        if positional.len() == n {
            Ok(())
        } else {
            Err(format!(
                "{verb}: expected {n} value(s), got {}",
                positional.len()
            ))
        }
    };

    let parsed = match verb {
        "set-volume" => {
            want(1)?;
            // The bounds come from the MCP tool, not from here: a range that
            // exists in two places is a range that will be changed in one.
            let raw = number(positional[0], verb)?;
            let value = crate::mcp_tools::need_int(&json!({ "level": raw }), "level", 0, 15)
                .map_err(|e| format!("{verb}: {e}"))?;
            Verb::SetVolume { value }
        }
        "set-brightness" => {
            want(1)?;
            let raw = number(positional[0], verb)?;
            let value = crate::mcp_tools::need_int(&json!({ "level": raw }), "level", 0, 100)
                .map_err(|e| format!("{verb}: {e}"))?;
            Verb::SetBrightness { value }
        }
        "set-radio" => {
            want(1)?;
            let raw = number(positional[0], verb)?;
            let freq_x10 =
                crate::mcp_tools::need_int(&json!({ "freq_x10": raw }), "freq_x10", 875, 1080)
                    .map_err(|e| format!("{verb}: {e}"))?;
            Verb::SetRadio { freq_x10 }
        }
        "set-alarm" => {
            want(1)?;
            let (hour, minute) = parse_hh_mm(positional[0], verb)?;
            Verb::SetAlarm {
                time: positional[0].to_string(),
                hour,
                minute,
            }
        }
        "set-temperature" => {
            want(2)?;
            let raw = number(positional[0], verb)?;
            // Range and the icon name are the tool's, not this file's.
            let temperature = crate::mcp_tools::need_int(
                &json!({ "temperature_c": raw }),
                "temperature_c",
                -127,
                128,
            )
            .map_err(|e| format!("{verb}: {e}"))?;
            let weather = positional[1].to_string();
            // Validate the name here so the refusal happens before a panel is
            // resolved, and let the tool map it to the wire value.
            crate::mcp_tools::weather_id(&weather).map_err(|e| format!("{verb}: {e}"))?;
            Verb::SetTemperature {
                temperature,
                weather,
            }
        }
        "push-image" | "push-gif" => {
            want(1)?;
            let path = positional[0].to_string();
            if !std::path::Path::new(&path).exists() {
                return Err(format!("{verb}: file not found: {path}"));
            }
            if verb == "push-gif" {
                Verb::PushGif { path }
            } else {
                Verb::PushImage { path }
            }
        }
        other => return Err(format!("divoomd: unknown verb {other:?}")),
    };

    Ok(VerbRequest {
        verb: parsed,
        mac,
        json: as_json,
    })
}

/// True for a bare negative integer like `-1`, which is a value and not a
/// cluster of short options.
fn is_negative_number(arg: &str) -> bool {
    arg.strip_prefix('-')
        .is_some_and(|rest| !rest.is_empty() && rest.parse::<i64>().is_ok())
}

/// Split `HH:MM` on a 24h clock, refusing anything else with the input quoted.
///
/// The CLI has always taken `HH:MM` here, so the verb takes the same thing: a
/// user with a script does not get a new format because the command moved.
fn parse_hh_mm(raw: &str, verb: &str) -> Result<(i64, i64), String> {
    let Some((h, m)) = raw.split_once(':') else {
        return Err(format!("{verb}: time must be HH:MM (24h), got {raw:?}"));
    };
    let parse_part = |part: &str, what: &str| -> Result<i64, String> {
        part.parse::<i64>()
            .map_err(|_| format!("{verb}: {what} must be a number in HH:MM, got {raw:?}"))
    };
    let hour = parse_part(h, "hour")?;
    let minute = parse_part(m, "minute")?;
    if !(0..=23).contains(&hour) {
        return Err(format!("{verb}: hour must be 0..23, got {hour}"));
    }
    if !(0..=59).contains(&minute) {
        return Err(format!("{verb}: minute must be 0..59, got {minute}"));
    }
    Ok((hour, minute))
}

/// A positional that must be a whole number. A non-number is an error, never a
/// zero: `set-volume loud` must not quietly mean `set-volume 0`.
fn number(raw: &str, verb: &str) -> Result<i64, String> {
    raw.parse::<i64>()
        .map_err(|_| format!("{verb}: {raw:?} is not a number"))
}

/// Put the target MAC into a tool's arguments, or leave the key out entirely.
///
/// The tool layer reads `mac` from the arguments it is handed, so a verb that
/// forgets this accepts `--mac`, reports success, and pushes to whichever panel
/// happens to be active. The key is absent rather than null when there is no
/// MAC, because `null` is a value the daemon would have to interpret.
fn put_mac(args: &mut Value, mac: Option<&str>) {
    if let Some(m) = mac {
        args["mac"] = json!(m);
    }
}

/// Perform the verb against a daemon and render its result.
///
/// # Errors
///
/// A message fit to print: what failed, and — for a transport failure — which
/// daemon. The daemon owns the device, so every failure here is a daemon that is
/// not running, a panel that is not connected, or a device that refused.
pub async fn run(request: &VerbRequest, target: &DaemonTarget) -> Result<VerbOutcome, String> {
    let mac = request.mac.as_deref();
    match &request.verb {
        // These two go through the MCP tool layer on purpose: it already holds
        // the argument bounds, the `device_call` method name and the result
        // shape, and a CLI verb that re-derived them would be a second
        // implementation of the same operation that could disagree with the
        // one an AI agent is calling.
        Verb::SetVolume { value } => {
            let mut tool_args = json!({ "level": value });
            put_mac(&mut tool_args, mac);
            let value_out = crate::mcp_tools::call_tool("set_volume", &tool_args, target).await?;
            Ok(VerbOutcome {
                human: format!("set volume to {value}/15"),
                value: value_out,
            })
        }
        Verb::SetBrightness { value } => {
            let mut tool_args = json!({ "level": value });
            put_mac(&mut tool_args, mac);
            let value_out =
                crate::mcp_tools::call_tool("set_brightness", &tool_args, target).await?;
            Ok(VerbOutcome {
                human: format!("set brightness to {value}%"),
                value: value_out,
            })
        }
        Verb::SetRadio { freq_x10 } => {
            let freq_x10 = *freq_x10;
            let mut tool_args = json!({ "freq_x10": freq_x10 });
            put_mac(&mut tool_args, mac);
            let out = crate::mcp_tools::call_tool("set_radio", &tool_args, target).await?;
            Ok(VerbOutcome {
                // Integer math rather than `freq_x10 as f64 / 10.0`: the cast
                // can lose precision, and `87.5` is exactly "87.5" this way.
                human: format!("tuned FM to {}.{} MHz", freq_x10 / 10, freq_x10 % 10),
                value: out,
            })
        }
        Verb::SetAlarm { time, hour, minute } => {
            // Alarm 0, every day (127), which is exactly what the CLI has always
            // set: `set-alarm` is the scriptable path and a full editor is the
            // GUI's job. `enabled` defaults to true in the tool, matching the
            // status byte the CLI sent (1 = on).
            //
            // NOTE a behaviour change: the CLI used to send `trigger_mode = 0`,
            // which the reference implementation never documents — it defines
            // the field as ALARM_TRIGGER_MUSIC=1 / ALARM_TRIGGER_GIF=4, and its
            // own usage example passes 1. The tool sends 1. So the byte on the
            // wire changes for this verb, from an undocumented value to the
            // documented one. See the CHANGELOG stanza.
            let mut tool_args = json!({
                "index": 0,
                "hour": hour,
                "minute": minute,
                "weekday_mask": 127,
            });
            put_mac(&mut tool_args, mac);
            let out = crate::mcp_tools::call_tool("set_alarm", &tool_args, target).await?;
            Ok(VerbOutcome {
                human: format!("set alarm 0 to {hour:02}:{minute:02} every day ({time})"),
                value: out,
            })
        }
        Verb::SetTemperature {
            temperature,
            weather,
        } => {
            let mut tool_args = json!({ "temperature_c": temperature, "weather": weather });
            put_mac(&mut tool_args, mac);
            let out = crate::mcp_tools::call_tool("set_weather", &tool_args, target).await?;
            Ok(VerbOutcome {
                human: format!("set weather: {temperature}°C, {weather}"),
                value: out,
            })
        }
        // These two deliberately do NOT go through the MCP `show_image` tool.
        // That tool decodes in the client and resizes to a hardcoded 16x16
        // (see `mcp_tools::push_image_bytes`); the daemon's own handler takes
        // the PATH and sizes to the panel's native resolution, handling
        // animation frames too. Routing the CLI through the tool would quietly
        // turn every 64x64 push into a 16x16 one.
        //
        // `push-gif` is not a special case: it is this same call under the name
        // scripts use, exactly as it was in Python.
        Verb::PushImage { path } | Verb::PushGif { path } => {
            let name = std::path::Path::new(path)
                .file_name()
                .map_or_else(|| path.clone(), |n| n.to_string_lossy().into_owned());
            let reply = mcp_daemon::dc(target, "display.show_image", json!([path]), mac).await?;
            let ok = reply
                .get("success")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            Ok(VerbOutcome {
                human: format!("pushed {name} to {}", mac.unwrap_or("the active panel")),
                value: json!({ "ok": ok, "file": path }),
            })
        }
    }
}

#[cfg(test)]
#[path = "verbs_tests.rs"]
mod tests;
