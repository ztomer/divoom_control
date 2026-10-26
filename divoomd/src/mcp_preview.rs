//! `get_screen_previews`: what each panel is showing, as an MCP tool (API.DV).
//!
//! READ-ONLY. It asks the daemon for `screen_previews` (WG.5a,
//! `crate::screen_previews`) -- the frames the daemon itself streamed to each
//! panel -- and sends nothing to any panel. Until this tool, the preview
//! reached only the socket and the `divoom-control preview` CLI.
//!
//! The reply is the CLI's shape (`divoom_lib/cli_preview.py`): `daemon`
//! (`state` + `reason`), `now_ms`, and one entry per panel carrying its own
//! `state` and `reason` -- only `state: "frame"` has pixels (house rule #12).
//! The pixels travel as MCP IMAGE content, one block per frame after the text
//! block; the entry's `frame.image` is that block's index in `content`, and
//! the base64 is not repeated in the structured reply.

use serde_json::{json, Value};

use crate::daemon_target::DaemonTarget;
use crate::error_code::ToolError;
use crate::mcp_catalog::{tool, Effect};

/// The name the tool is listed under.
pub const NAME: &str = "get_screen_previews";

/// This file's tool, in catalog form.
pub fn catalog() -> Vec<Value> {
    // The name is spelled out (not `NAME`) so the catalog readers that grep
    // `tool("...")` (tools/check_hw_verify_methods.py) see it; the test
    // below holds the two together.
    vec![tool(
        "get_screen_previews",
        Effect::Read,
        &[
            ("daemon", "object"),
            ("now_ms", "any"),
            ("devices", "array"),
        ],
        "What each panel is showing, as the daemon put it there: one entry per panel with its \
         state and reason (frame, nothing_sent, device_rendered, undecoded, offline), and every \
         frame as an image (frame.image is its index in the reply's content). Sends nothing to \
         any panel.",
        &json!({"type":"object","properties":{}}),
    )]
}

/// One image block for the MCP layer: base64 data and its MIME type.
pub struct Image {
    pub data: String,
    pub mime: String,
}

/// The answer and the images it refers to.
pub struct Preview {
    pub structured: Value,
    pub images: Vec<Image>,
}

/// Ask the daemon, and shape its answer. A daemon that is not running or
/// predates `screen_previews` is an ANSWER (its `daemon.state` says which),
/// not a tool failure; a refusal (an unknown `mac`) is a failure with the
/// daemon's code.
///
/// # Errors
///
/// When the daemon refuses the read.
pub async fn call(a: &Value, target: &DaemonTarget) -> Result<Preview, ToolError> {
    let args = a
        .get("mac")
        .and_then(Value::as_str)
        .map_or_else(|| json!({}), |m| json!({ "mac": m }));
    let reply = match crate::mcp_daemon::cmd(target, "screen_previews", args).await {
        Ok(reply) => reply,
        Err(why) => return Ok(absent("not_running", &why)),
    };
    if reply.get("code").and_then(Value::as_str) == Some("unknown_command") {
        return Ok(absent(
            "unsupported",
            "the running divoomd predates screen_previews; update the Divoom app to read previews",
        ));
    }
    let reply = crate::mcp_daemon::check(reply)?;
    Ok(split(&reply))
}

fn absent(state: &str, reason: &str) -> Preview {
    Preview {
        structured: json!({
            "daemon": { "state": state, "reason": reason },
            "now_ms": null,
            "devices": [],
        }),
        images: Vec::new(),
    }
}

/// Move every frame's pixels out of the reply into image blocks. Block 0 of
/// the content is the text, so the first image is index 1.
fn split(reply: &Value) -> Preview {
    let mut images = Vec::new();
    let mut devices = reply
        .get("devices")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for d in &mut devices {
        let Some(frame) = d.get_mut("frame").and_then(Value::as_object_mut) else {
            continue;
        };
        let url = frame
            .remove("data_url")
            .and_then(|v| v.as_str().map(str::to_string));
        let Some((head, data)) = url.as_deref().and_then(|u| u.split_once(',')) else {
            continue;
        };
        let mime = head
            .strip_prefix("data:")
            .and_then(|r| r.split(';').next())
            .unwrap_or("application/octet-stream")
            .to_string();
        frame.insert("image".into(), json!(images.len() + 1));
        images.push(Image {
            data: data.to_string(),
            mime,
        });
    }
    Preview {
        structured: json!({
            "daemon": { "state": "running", "reason": null },
            "now_ms": reply.get("now_ms").cloned().unwrap_or(Value::Null),
            "devices": devices,
        }),
        images,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

    #[test]
    fn the_catalog_lists_the_tool_under_its_name() {
        assert_eq!(catalog()[0]["name"], json!(NAME));
    }

    #[tokio::test]
    async fn no_daemon_is_an_answer_that_says_so() {
        let p = call(&json!({}), &unreachable()).await.expect("an answer");
        assert_eq!(p.structured["daemon"]["state"], json!("not_running"));
        assert!(p.structured["daemon"]["reason"].is_string());
        assert_eq!(p.structured["devices"], json!([]));
        assert_eq!(p.images.len(), 0);
    }

    #[tokio::test]
    async fn an_old_daemon_is_unsupported_not_a_failure() {
        let d = FakeDaemon::replying(
            json!({ "success": false, "error": "unknown command", "code": "unknown_command" }),
            None,
        )
        .await;
        let p = call(&json!({}), &d.target).await.expect("an answer");
        assert_eq!(p.structured["daemon"]["state"], json!("unsupported"));
    }

    #[tokio::test]
    async fn an_unknown_panel_is_a_refusal_with_its_code() {
        let d = FakeDaemon::replying(
            json!({ "success": false, "error": "no panel 'X'", "code": "unknown_device" }),
            None,
        )
        .await;
        let e = call(&json!({ "mac": "X" }), &d.target)
            .await
            .err()
            .expect("refused");
        assert_eq!(e.code.as_deref(), Some("unknown_device"));
        assert_eq!(d.requests()[0]["args"], json!({ "mac": "X" }));
    }

    #[tokio::test]
    async fn frames_become_images_and_every_entry_keeps_its_state() {
        let d = FakeDaemon::replying(
            json!({ "success": true, "now_ms": 5, "devices": [
                { "id": "A", "state": "frame", "reason": null,
                  "frame": { "data_url": "data:image/png;base64,iVBO", "mime": "image/png",
                             "width": 16, "height": 16, "frames": 1 } },
                { "id": "B", "state": "offline", "reason": "no link", "frame": null },
            ]}),
            None,
        )
        .await;
        let p = call(&json!({}), &d.target).await.expect("an answer");
        assert_eq!(d.requests()[0]["command"], json!("screen_previews"));
        assert_eq!(p.images.len(), 1);
        assert_eq!(p.images[0].data, "iVBO");
        assert_eq!(p.images[0].mime, "image/png");
        let devs = &p.structured["devices"];
        assert_eq!(devs[0]["frame"]["image"], json!(1));
        assert!(devs[0]["frame"].get("data_url").is_none(), "no second copy");
        assert_eq!(devs[1]["state"], json!("offline"));
        assert_eq!(devs[1]["reason"], json!("no link"));
        assert_eq!(p.structured["daemon"]["state"], json!("running"));
        assert_eq!(p.structured["now_ms"], json!(5));
    }
}
