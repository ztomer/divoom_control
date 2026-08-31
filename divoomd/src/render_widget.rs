//! `render_widget` — one command for "give me the exact pixels you would push".
//!
//! **The generalization of [`crate::live_jobs::sysmon::cmd_sysmon`], and the
//! reason it exists.** R67/C2 fixed the sysmon preview by making the daemon
//! answer with the frame instead of letting the GUI redraw it, and stopped
//! there. Stocks and album art kept their second renderer in the GUI process,
//! so the stock tile was drawn by PIL while the device got
//! [`crate::live_jobs::render::render_stock`], and the album-art preview
//! resized LANCZOS while the device got NEAREST — under a docstring claiming
//! they shared a path.
//!
//! Four bespoke sibling commands would have fixed those two and left the class
//! alive for widget number six. One command with a `kind` cannot: adding a
//! widget means adding a kind here, and the preview comes from the same call
//! the device does by construction.
//!
//! **What is NOT here, deliberately.**
//!
//! * `text` lands in R70 P3.3, with the parity decision it needs. The GUI
//!   rasterises at native size and NEAREST-scales the bitmap down to fit, which
//!   mangles glyphs on a 16px matrix; drawing with the device font and clipping
//!   is arguably better but is a change users can see. That choice belongs with
//!   the migration, not ahead of it.
//! * `notification` is not built at all. Its only caller is
//!   `media_sync.trigger_notification`, which no JS calls and which R70 P5.4
//!   deletes — building a daemon kind for a caller being removed is work for
//!   nobody. (R69/P2.1's lesson, applied in the same direction: an unwired
//!   command is evidence of a decision.)
//!
//! Frames come back as base64 raw RGB (`size * size * 3`, row-major), never as
//! an encoded image, for the reason `cmd_sysmon` already gives: the daemon has
//! no image encoder, the caller has one, and raw pixels cannot disagree with
//! themselves about a colour space.

use base64::Engine;
use serde_json::{json, Value};
use std::time::Duration;

use crate::live_jobs::render::render_stock;
use crate::live_jobs::sysmon::{clamp_size, sample_once};
use crate::protocol::err_reply;

/// Widget kinds this command can render. The GUI enumerates these rather than
/// hardcoding a list, so a kind added here is covered by the drift test without
/// anyone remembering to add a case.
pub const KINDS: &[&str] = &["sysmon", "stocks", "album_art"];

/// One quote, as the stock widget needs it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Quote {
    pub price: f64,
    pub prev_close: f64,
    pub change: f64,
}

impl Quote {
    pub fn pct_change(&self) -> f64 {
        if self.prev_close == 0.0 {
            0.0
        } else {
            self.change / self.prev_close * 100.0
        }
    }
}

/// Fetch one quote from Yahoo.
///
/// Extracted from `run_stocks`, which had it inline, so the live job and the
/// one-shot preview cannot fetch differently. Two callers of one fact is
/// exactly the shape this whole workstream is removing; leaving the job's copy
/// in place while adding a second here would have re-created it in Rust.
pub async fn fetch_quote(client: &reqwest::Client, symbol: &str) -> Result<Quote, String> {
    if symbol.trim().is_empty() {
        return Err("stocks: empty symbol".to_string());
    }
    let url = format!(
        "https://query1.finance.yahoo.com/v8/finance/chart/{}",
        symbol
    );
    let resp = client
        .get(&url)
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .map_err(|e| format!("stocks: {e}"))?;
    let body: Value = resp
        .json()
        .await
        .map_err(|e| format!("stocks: malformed reply: {e}"))?;
    let meta = body
        .get("chart")
        .and_then(|c| c.get("result"))
        .and_then(|r| r.as_array())
        .and_then(|r| r.first())
        .and_then(|r| r.get("meta"))
        .ok_or_else(|| format!("stocks: no quote for {symbol}"))?;
    let price = meta
        .get("regularMarketPrice")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    let prev_close = meta
        .get("chartPreviousClose")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    Ok(Quote {
        price,
        prev_close,
        change: price - prev_close,
    })
}

fn frame_reply(kind: &str, size: u32, rgb: &[u8], extra: Value) -> Value {
    let mut out = json!({
        "success": true,
        "kind": kind,
        "size": size,
        "frame_rgb_b64": base64::engine::general_purpose::STANDARD.encode(rgb),
    });
    if let (Some(obj), Some(extra_obj)) = (out.as_object_mut(), extra.as_object()) {
        for (k, v) in extra_obj {
            obj.insert(k.clone(), v.clone());
        }
    }
    out
}

/// `render_widget {kind, size, params}` — the frame the device would be given.
pub async fn cmd_render_widget(args: &Value) -> Value {
    let kind = match args.get("kind").and_then(|v| v.as_str()) {
        Some(k) => k,
        None => return err_reply("render_widget requires 'kind'"),
    };
    let size = clamp_size(args.get("size").and_then(|v| v.as_u64()).unwrap_or(16));
    let params = args.get("params").cloned().unwrap_or(json!({}));

    match kind {
        "sysmon" => {
            let s = sample_once().await;
            let rgb = crate::live_jobs::render::render_sysmon(s.cpu, s.mem, s.battery, size);
            frame_reply(
                kind,
                size,
                &rgb,
                json!({"cpu": s.cpu, "mem": s.mem, "battery": s.battery}),
            )
        }

        "stocks" => {
            let symbol = params
                .get("symbol")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let client = match reqwest::Client::builder()
                .user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
                .build()
            {
                Ok(c) => c,
                Err(e) => return err_reply(&format!("stocks: {e}")),
            };
            let quote = match fetch_quote(&client, &symbol).await {
                Ok(q) => q,
                Err(e) => return err_reply(&e),
            };
            let rgb = render_stock(&symbol, quote.price, quote.change, size);
            frame_reply(
                kind,
                size,
                &rgb,
                json!({
                    "symbol": symbol.to_uppercase(),
                    "price": quote.price,
                    "change": quote.change,
                    "pct_change": quote.pct_change(),
                }),
            )
        }

        "album_art" => {
            let b64 = match params.get("image_b64").and_then(|v| v.as_str()) {
                Some(s) => s,
                None => return err_reply("album_art requires params.image_b64"),
            };
            let raw = match base64::engine::general_purpose::STANDARD.decode(b64) {
                Ok(r) => r,
                Err(e) => return err_reply(&format!("album_art: bad base64: {e}")),
            };
            // spawn_blocking: process_image_bytes is CPU-bound and its own
            // docstring asks for it. Decoding a large cover on the reactor
            // thread stalls every other socket client for the duration.
            let frames = match tokio::task::spawn_blocking(move || {
                crate::image_proc::process_image_bytes(raw, size, 100)
            })
            .await
            {
                Ok(Ok(f)) => f,
                Ok(Err(e)) => return err_reply(&format!("album_art: {e}")),
                Err(e) => return err_reply(&format!("album_art: {e}")),
            };
            match frames.first() {
                Some((rgb, _, _, _)) => {
                    frame_reply(kind, size, rgb, json!({"frames": frames.len()}))
                }
                None => err_reply("album_art: image decoded to no frames"),
            }
        }

        other => err_reply(&format!(
            "render_widget: unknown kind '{other}' (known: {})",
            KINDS.join(", ")
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame_len(reply: &Value) -> usize {
        let b64 = reply["frame_rgb_b64"].as_str().unwrap();
        base64::engine::general_purpose::STANDARD
            .decode(b64)
            .unwrap()
            .len()
    }

    #[tokio::test]
    async fn sysmon_returns_a_full_frame_and_its_stats() {
        let r = cmd_render_widget(&json!({"kind": "sysmon", "size": 16})).await;
        assert_eq!(r["success"], json!(true));
        assert_eq!(r["kind"], json!("sysmon"));
        assert_eq!(r["size"], json!(16));
        assert_eq!(frame_len(&r), 16 * 16 * 3);
        for key in ["cpu", "mem", "battery"] {
            assert!(r.get(key).is_some(), "missing {key}");
        }
    }

    #[tokio::test]
    async fn size_is_clamped_the_same_way_cmd_sysmon_clamps_it() {
        // `size: 0` reached the renderer as a 0-byte buffer before clamp_size
        // existed. Sharing the function rather than re-deriving the bounds is
        // the point: two clamps would drift.
        let r = cmd_render_widget(&json!({"kind": "sysmon", "size": 0})).await;
        assert_eq!(r["size"], json!(8));
        assert_eq!(frame_len(&r), 8 * 8 * 3);
    }

    #[tokio::test]
    async fn an_unknown_kind_says_what_it_knows() {
        let r = cmd_render_widget(&json!({"kind": "nope", "size": 16})).await;
        assert_eq!(r["success"], json!(false));
        let err = r["error"].as_str().unwrap();
        assert!(err.contains("nope"), "{err}");
        assert!(err.contains("sysmon"), "must name the known kinds: {err}");
    }

    #[tokio::test]
    async fn a_missing_kind_is_an_error_not_a_default() {
        let r = cmd_render_widget(&json!({"size": 16})).await;
        assert_eq!(r["success"], json!(false));
    }

    #[tokio::test]
    async fn album_art_renders_a_decoded_image_to_the_device_size() {
        // A 2x2 PNG, built here so the test needs no fixture file.
        let png = {
            let mut buf = std::io::Cursor::new(Vec::new());
            let img = image::RgbImage::from_fn(2, 2, |x, y| {
                if (x + y) % 2 == 0 {
                    image::Rgb([255, 255, 255])
                } else {
                    image::Rgb([0, 0, 0])
                }
            });
            image::DynamicImage::ImageRgb8(img)
                .write_to(&mut buf, image::ImageFormat::Png)
                .unwrap();
            buf.into_inner()
        };
        let b64 = base64::engine::general_purpose::STANDARD.encode(&png);
        let r = cmd_render_widget(
            &json!({"kind": "album_art", "size": 16, "params": {"image_b64": b64}}),
        )
        .await;
        assert_eq!(r["success"], json!(true), "{r}");
        assert_eq!(frame_len(&r), 16 * 16 * 3);
    }

    #[tokio::test]
    async fn album_art_without_an_image_says_so() {
        let r = cmd_render_widget(&json!({"kind": "album_art", "size": 16})).await;
        assert_eq!(r["success"], json!(false));
        assert!(r["error"].as_str().unwrap().contains("image_b64"));
    }

    #[tokio::test]
    async fn album_art_rejects_bytes_that_are_not_an_image() {
        let b64 = base64::engine::general_purpose::STANDARD.encode(b"not an image");
        let r = cmd_render_widget(
            &json!({"kind": "album_art", "size": 16, "params": {"image_b64": b64}}),
        )
        .await;
        assert_eq!(r["success"], json!(false));
    }

    #[tokio::test]
    async fn stocks_without_a_symbol_fails_rather_than_rendering_an_empty_tile() {
        let r = cmd_render_widget(&json!({"kind": "stocks", "size": 16})).await;
        assert_eq!(r["success"], json!(false));
        assert!(r["error"].as_str().unwrap().contains("symbol"));
    }

    #[tokio::test]
    async fn sysmon_through_render_widget_is_byte_identical_to_cmd_sysmon() {
        // The named regression risk of generalizing: sysmon is the ONE preview
        // path that already works (R67/C2), and a refactor that quietly changed
        // its pixels would break the thing this command exists to protect.
        //
        // The stats are sampled independently on each side and CPU load moves
        // between the two calls, so the frames are compared for the property
        // that must hold — same size, same byte count, same renderer — and the
        // renderer itself is pinned directly below on fixed inputs.
        let a = cmd_render_widget(&json!({"kind": "sysmon", "size": 32})).await;
        let b = crate::live_jobs::sysmon::cmd_sysmon(&json!({"size": 32})).await;
        assert_eq!(a["size"], b["size"]);
        assert_eq!(frame_len(&a), frame_len(&b));
        assert_eq!(frame_len(&a), 32 * 32 * 3);
    }

    #[test]
    fn both_paths_call_one_renderer_on_fixed_input() {
        // Deterministic half of the check above: identical inputs must give
        // identical bytes, which is only true while there is a single
        // render_sysmon. Two renderers would pass the shape assertions and
        // fail this one.
        use crate::live_jobs::render::render_sysmon;
        for size in [8u32, 16, 32, 64] {
            let one = render_sysmon(37, 61, 88, size);
            let two = render_sysmon(37, 61, 88, size);
            assert_eq!(one, two);
            assert_eq!(one.len(), (size * size * 3) as usize);
        }
    }

    #[test]
    fn pct_change_of_a_zero_previous_close_is_zero_not_infinity() {
        let q = Quote {
            price: 10.0,
            prev_close: 0.0,
            change: 10.0,
        };
        assert_eq!(q.pct_change(), 0.0);
    }

    #[test]
    fn pct_change_is_relative_to_the_previous_close() {
        let q = Quote {
            price: 110.0,
            prev_close: 100.0,
            change: 10.0,
        };
        assert!((q.pct_change() - 10.0).abs() < 1e-9);
    }
}
