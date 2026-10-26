//! The one shape every MCP tool entry has: name, what it does to the world,
//! what a success returns, a description and the input schema.
//!
//! The effect and the reply's shape are declared HERE, beside each tool in the
//! catalog (`mcp_tools::catalog`, `mcp_more_tools::catalog`,
//! `mcp_preview::catalog`), never in a second list in the MCP layer -- a second
//! list is the drift a registry exists to remove. The entry is MCP's own JSON
//! (`annotations`, `outputSchema`), so `crate::mcp` hands it to rmcp as it is.

use serde_json::{json, Map, Value};

/// What a tool does to the world. Decides its MCP annotations and whether a
/// server started without `--allow-destructive` offers it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Effect {
    /// Reads the daemon's or a panel's state; sends nothing to a panel.
    Read,
    /// Sends to a panel or changes its state, in a way the caller can read
    /// back and restore (volume, brightness, the channel) or that is
    /// transient by nature (a drawn image, text, a notification, a live
    /// widget, a lease). Listed by default.
    Write,
    /// Overwrites panel state the daemon cannot read back, so the previous
    /// value is lost (a stored alarm, the orientation, low-power mode, the
    /// radio frequency). Listed and callable only with `--allow-destructive`.
    Destructive,
}

impl Effect {
    /// MCP's four hints, every one stated: the spec's defaults for an
    /// unstated hint (destructive, open-world) are the alarming ones.
    fn annotations(self, open_world: bool) -> Value {
        json!({
            "readOnlyHint": self == Self::Read,
            "destructiveHint": self == Self::Destructive,
            "idempotentHint": self == Self::Read,
            "openWorldHint": open_world,
        })
    }
}

/// `{"type":"object"}` listing `returns` -- `(field, json type)`, every one
/// carried by every success; type `"any"` leaves the field unconstrained (a
/// value that may be null, or the daemon's own object).
fn output_schema(returns: &[(&str, &str)]) -> Value {
    let mut props = Map::new();
    for (field, ty) in returns {
        let schema = if *ty == "any" {
            json!({})
        } else {
            json!({ "type": ty })
        };
        props.insert((*field).to_string(), schema);
    }
    let required: Vec<&str> = returns.iter().map(|(f, _)| *f).collect();
    json!({ "type": "object", "properties": props, "required": required })
}

/// A tool's `tools/list` entry.
///
/// Every tool that can name a panel takes `mac`, and every tool that can
/// reach one takes the caller's `lease`: one seam, so no tool is the one that
/// forgot it.
pub fn tool(
    name: &str,
    effect: Effect,
    returns: &[(&str, &str)],
    desc: &str,
    schema: &Value,
) -> Value {
    let mut s = schema.clone();
    if let Some(props) = s.get_mut("properties").and_then(Value::as_object_mut) {
        if name != "list_screens" {
            props.insert(
                "mac".into(),
                json!({
                    "type": "string",
                    "description": "Optional MAC address of the target display (default: active display)."
                }),
            );
        }
        if !matches!(
            name,
            "list_screens" | "lease_acquire" | "get_screen_previews"
        ) {
            props.entry("lease").or_insert_with(|| {
                json!({
                    "type": "string",
                    "description": "The token from lease_acquire, while you hold the panel's lease."
                })
            });
        }
    }
    // A live widget fetches stock quotes and weather from the internet; every
    // other tool's world is the daemon and its panels.
    let open_world = name == "live_job_start";
    json!({
        "name": name,
        "description": desc,
        "inputSchema": s,
        "outputSchema": output_schema(returns),
        "annotations": effect.annotations(open_world),
    })
}

/// True when the entry is a destructive tool (its annotation says so).
#[must_use]
pub fn is_destructive(entry: &Value) -> bool {
    entry["annotations"]["destructiveHint"] == json!(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_hint_is_stated_and_only_read_is_read_only() {
        for (effect, ro, de) in [
            (Effect::Read, true, false),
            (Effect::Write, false, false),
            (Effect::Destructive, false, true),
        ] {
            let t = tool(
                "t",
                effect,
                &[],
                "d",
                &json!({"type":"object","properties":{}}),
            );
            let a = &t["annotations"];
            assert_eq!(a["readOnlyHint"], json!(ro), "{effect:?}");
            assert_eq!(a["destructiveHint"], json!(de), "{effect:?}");
            assert!(a["idempotentHint"].is_boolean() && a["openWorldHint"].is_boolean());
            assert_eq!(is_destructive(&t), de);
        }
    }

    #[test]
    fn the_output_schema_is_an_object_requiring_what_it_lists() {
        let t = tool(
            "t",
            Effect::Write,
            &[("ok", "boolean"), ("v", "any")],
            "d",
            &json!({"type":"object","properties":{}}),
        );
        assert_eq!(
            t["outputSchema"],
            json!({"type":"object","properties":{"ok":{"type":"boolean"},"v":{}},"required":["ok","v"]})
        );
    }
}
