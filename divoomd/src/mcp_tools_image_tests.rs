//! `show_image` at the panel's own size, under a stated resize policy (P4.3).
//!
//! Split from `mcp_tools_tests.rs` by the 500-line cap: these are the image
//! tools' tests, end to end against a fake daemon that records what it is sent.

use super::*;
use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

/// A 16x8 PNG on disk, every pixel lit.
fn wide_png(tag: &str) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!("divoom_mcp_{tag}_{}.png", std::process::id()));
    image::RgbImage::from_pixel(16, 8, image::Rgb([250, 10, 10]))
        .save(&path)
        .expect("write png");
    path
}

fn shown(daemon: &FakeDaemon) -> Value {
    daemon
        .requests()
        .into_iter()
        .find(|r| r["args"]["method"] == json!("show_image"))
        .expect("a show_image call")
}

#[tokio::test]
async fn show_image_draws_at_the_panels_size() {
    let daemon = FakeDaemon::replying(
        json!({ "success": true, "width": 64, "height": 64, "result": true }),
        None,
    )
    .await;
    let png = wide_png("fit");
    let reply = call_tool(
        "show_image",
        &json!({ "file": png.to_str(), "mac": "AA" }),
        &daemon.target,
    )
    .await
    .expect("shown");
    assert_eq!(reply["size"], json!(64), "{reply}");
    assert_eq!(reply["resize"], json!("fit"), "{reply}");
    let status = &daemon.requests()[0];
    assert_eq!(status["command"], json!("device_status"), "{status}");
    assert_eq!(status["args"]["mac"], json!("AA"), "{status}");
    let kw = &shown(&daemon)["args"]["kwargs"];
    assert_eq!(kw["w"], json!(64));
    assert_eq!(kw["h"], json!(64));
    assert_eq!(kw["rgb"].as_array().map(Vec::len), Some(64 * 64 * 3));
    let _ = std::fs::remove_file(png);
}

#[tokio::test]
async fn resize_none_with_the_wrong_size_is_refused_before_anything_is_sent() {
    let daemon = FakeDaemon::replying(
        json!({ "success": true, "width": 64, "height": 64, "result": true }),
        None,
    )
    .await;
    let png = wide_png("none");
    let err = call_tool(
        "show_image",
        &json!({ "file": png.to_str(), "resize": "none" }),
        &daemon.target,
    )
    .await
    .expect_err("16x8 is not 64x64");
    assert!(err.contains("64x64") && err.contains("16x8"), "{err}");
    assert!(
        daemon
            .requests()
            .iter()
            .all(|r| r["args"]["method"] != json!("show_image")),
        "nothing may be drawn"
    );
    let _ = std::fs::remove_file(png);
}

#[tokio::test]
async fn an_unknown_panel_size_must_be_given_not_guessed() {
    let daemon = FakeDaemon::replying(
        json!({ "success": true, "width": null, "result": true }),
        None,
    )
    .await;
    let png = wide_png("unknown");
    let err = call_tool(
        "show_image",
        &json!({ "file": png.to_str() }),
        &daemon.target,
    )
    .await
    .expect_err("no size to draw at");
    assert!(err.contains("size"), "{err}");
    call_tool(
        "show_image",
        &json!({ "file": png.to_str(), "size": 32 }),
        &daemon.target,
    )
    .await
    .expect("an explicit size is enough");
    assert_eq!(shown(&daemon)["args"]["kwargs"]["w"], json!(32));
    let _ = std::fs::remove_file(png);
}

#[tokio::test]
async fn an_unknown_resize_policy_is_rejected_by_name() {
    let err = call_tool(
        "show_image",
        &json!({ "file": "/nonexistent.png", "resize": "stretch" }),
        &unreachable(),
    )
    .await
    .expect_err("not a policy");
    assert!(err.contains("resize"), "{err}");
}
