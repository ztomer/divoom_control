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

use crate::live_jobs::render::{render_stock, render_text};
use crate::live_jobs::sysmon::{clamp_size, sample_once};
use crate::protocol::err_reply;

/// Widget kinds this command can render. The GUI enumerates these rather than
/// hardcoding a list, so a kind added here is covered by the drift test without
/// anyone remembering to add a case.
pub const KINDS: &[&str] = &["sysmon", "stocks", "album_art", "text"];

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

/// `#RRGGBB` (or bare `RRGGBB`) to RGB; white for anything unparseable.
///
/// White rather than black on a bad value: a mistyped colour should show the
/// text, not a blank matrix that looks like the feature is broken.
fn parse_color(raw: Option<&str>) -> (u8, u8, u8) {
    let s = raw.unwrap_or("").trim().trim_start_matches('#');
    if s.len() == 6 {
        if let (Ok(r), Ok(g), Ok(b)) = (
            u8::from_str_radix(&s[0..2], 16),
            u8::from_str_radix(&s[2..4], 16),
            u8::from_str_radix(&s[4..6], 16),
        ) {
            return (r, g, b);
        }
    }
    (255, 255, 255)
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

        "text" => {
            let text = params.get("text").and_then(|v| v.as_str()).unwrap_or("");
            if text.trim().is_empty() {
                return err_reply("text requires params.text");
            }
            // `font_size <= 1` selects the half-size glyphs, and so does any
            // 16px matrix — the same rule the GUI applied, kept so the choice
            // does not silently change for existing callers.
            let font_size = params
                .get("font_size")
                .and_then(|v| v.as_i64())
                .unwrap_or(1);
            let full_font = font_size > 1 && size > 16;
            let color = parse_color(params.get("color").and_then(|v| v.as_str()));
            let rgb = render_text(text, color, size, full_font);
            frame_reply(
                kind,
                size,
                &rgb,
                json!({"text": text, "full_font": full_font}),
            )
        }

        other => err_reply(&format!(
            "render_widget: unknown kind '{other}' (known: {})",
            KINDS.join(", ")
        )),
    }
}
