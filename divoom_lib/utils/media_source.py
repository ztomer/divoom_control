#!/usr/bin/env python3
"""
media_source.py — Advanced data sources for Divoom displays.
Fetches live macOS album artwork (Spotify/Apple Music), current date/time widgets,
and stock/crypto tickers, rendering them dynamically onto pixel grids.
"""

import subprocess
import sys
import urllib.request
import urllib.parse
import json
import logging
from pathlib import Path
from PIL import Image, ImageDraw

from divoom_lib.fonts import get_small_font

logger = logging.getLogger(__name__)


# ── now-playing REMOVED (R67/C2, 2026-08-29) ──────────────────────────────
#
# `get_current_playing_track`, `fetch_album_art_url` and
# `render_and_downsample_artwork` lived here and were a SECOND implementation of
# what divoomd already did in Rust. Both drove AppleScript at each player in
# turn and then guessed a cover-art URL from the iTunes Search API — a guess
# that cannot resolve non-album content (YouTube Music, podcasts, live sets) and
# needs a network round trip in order to fail. Running in the GUI process is
# also why the GUI was the thing asking for Apple Music access.
#
# The daemon now owns the question and answers it from macOS MediaRemote, which
# returns the exact image the player is displaying, as bytes, for every player
# that publishes to Now Playing — with no per-app Automation grant. Ask it:
#
#     DaemonClient().now_playing(include_artwork=True)
#
# See the `nowplaying` crate and divoomd/src/now_playing.rs.

def fetch_stock_ticker(symbol: str) -> dict | None:
    """
    Fetches live stock or crypto price using Yahoo Finance public API.
    symbol: e.g. "AAPL", "GOOG", "BTC-USD".
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=2m"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chart = data.get("chart", {})
            result = chart.get("result", [])
            if result:
                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("chartPreviousClose")
                change = price - prev_close if price and prev_close else 0
                pct_change = (change / prev_close) * 100 if prev_close else 0
                return {
                    "price": round(price, 2) if price else 0,
                    "change": round(change, 2),
                    "pct_change": round(pct_change, 2)
                }
    except Exception as e:
        logger.warning(f"Yahoo stock price query for {symbol} failed: {e}")
    return None


def render_stock_ticker_frame(symbol: str, data: dict, size: int = 16) -> Path:
    """
    Renders a neat visual stock ticker to fit Divoom grid dimensions (16x16 or 32x32).
    Shows the symbol name, current price, and green up-arrow / red down-arrow indicating change.
    """
    scratch_dir = Path(__file__).parent.parent.parent / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    out_path = scratch_dir / f"ticker_{symbol}_{size}.png"
    
    img = Image.new("RGB", (size, size), (5, 6, 12)) # Dark slate bg
    draw = ImageDraw.Draw(img)
    font = get_small_font()

    # Text colors
    is_up = data["change"] >= 0
    text_color = (0, 255, 180) if is_up else (255, 60, 60) # Green vs Red

    if size == 16:
        # Mini 16x16 layout: small arrow at top, then the ticker acronym in the
        # crisp bitmap font (R28 — no anti-aliasing at 16px). Only whole glyphs
        # that fit the 16px row are drawn (max_width); ~2-3 chars fit.
        if is_up:
            draw.polygon([(8, 0), (5, 4), (11, 4)], fill=text_color)  # small up triangle
        else:
            draw.polygon([(8, 4), (5, 0), (11, 0)], fill=text_color)  # small down triangle
        font.draw_text(draw, (0, 6), symbol.upper(), (255, 255, 255), max_width=size)
    else:
        # 32x32+ layout allows the full ticker + price in the bitmap font.
        font.draw_text(draw, (2, 2), symbol.upper()[:6], (255, 255, 255), max_width=size - 2)
        # Draw arrow (smaller than before)
        if is_up:
            draw.polygon([(25, 4), (21, 10), (29, 10)], fill=text_color)
        else:
            draw.polygon([(25, 10), (21, 4), (29, 4)], fill=text_color)
        # Draw price
        font.draw_text(draw, (2, 16), f"${data['price']}", text_color, max_width=size - 2)

    img.save(out_path)
    return out_path


def get_system_stats() -> dict:
    """Return live host metrics for an on-device system monitor (ported from the
    Wi-Fi-only Pixoo64-Advanced-Tools concept, rendered to a frame for BLE)."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.0)
        mem = psutil.virtual_memory().percent
        battery = None
        try:
            b = psutil.sensors_battery()
            battery = int(b.percent) if b else None
        except Exception:
            battery = None
        return {"cpu": round(cpu), "mem": round(mem), "battery": battery}
    except Exception as e:
        logger.warning(f"get_system_stats failed: {e}")
        return {"cpu": 0, "mem": 0, "battery": None}


def render_system_stats_frame(stats: dict, size: int = 16) -> Path:
    """Render CPU, RAM, and Battery as three labeled bar gauges sized to the
    device matrix. Mirrors render_stock_ticker_frame's approach."""
    scratch_dir = Path(__file__).parent.parent.parent / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    out_path = scratch_dir / f"sysmon_{size}.png"

    img = Image.new("RGB", (size, size), (5, 6, 12))
    draw = ImageDraw.Draw(img)

    def draw_gauge(x, y, w_max, h, value, color):
        # R18 item 4: no gray track box behind the bar — just the coloured fill
        # on the dark background (the empty grey rectangle read as unwanted
        # "white/gray background" on the device).
        frac = max(0.0, min(1.0, value / 100.0))
        w_fill = max(1, int(round(w_max * frac)))
        draw.rectangle([(x, y), (x + w_fill - 1, y + h - 1)], fill=color)

    cpu = stats.get("cpu", 0)
    mem = stats.get("mem", 0)
    bat = stats.get("battery")
    if bat is None:
        bat = 100

    cpu_color = (255, 200, 0)     # yellow
    mem_color = (90, 170, 255)    # blue
    bat_color = (255, 60, 60)     # red

    if size <= 16:
        draw_gauge(1, 1, 14, 3, cpu, cpu_color)
        draw_gauge(1, 6, 14, 3, mem, mem_color)
        draw_gauge(1, 11, 14, 3, bat, bat_color)
    else:
        # Larger layouts (e.g. 32x32, 64x64)
        scale = size / 32.0
        
        y_cpu_text = int(round(0 * scale))
        y_cpu_bar = int(round(6 * scale))
        y_mem_text = int(round(10 * scale))
        y_mem_bar = int(round(16 * scale))
        y_bat_text = int(round(20 * scale))
        y_bat_bar = int(round(26 * scale))
        
        bar_w = int(round(28 * scale))
        bar_h = int(round(3 * scale))
        
        if bar_h < 3:
            bar_h = 3
            
        draw_gauge(2, y_cpu_bar, bar_w, bar_h, cpu, cpu_color)
        
        draw_gauge(2, y_mem_bar, bar_w, bar_h, mem, mem_color)
        
        draw_gauge(2, y_bat_bar, bar_w, bar_h, bat, bat_color)

    img.save(out_path)
    return out_path


def render_notification_frame(app_name: str, size: int = 16) -> Path:
    """
    Renders a pixel-art notification frame for Mail, WhatsApp, or Telegram.
    Saves it as a PNG and returns the path.
    """
    scratch_dir = Path(__file__).parent.parent.parent / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    out_path = scratch_dir / f"notification_{app_name}_{size}.png"
    
    img = Image.new("RGB", (size, size), (5, 6, 12)) # Dark slate bg
    draw = ImageDraw.Draw(img)
    
    app_lower = app_name.lower()
    scale = size / 16.0
    
    if app_lower == "mail":
        # Draw a beautiful retro envelope
        left = int(2 * scale)
        top = int(4 * scale)
        right = int(13 * scale)
        bottom = int(11 * scale)
        
        draw.rectangle([(left, top), (right, bottom)], fill=(40, 42, 54), outline=(255, 255, 255))
        mid_x = int(7 * scale)
        mid_y = int(8 * scale)
        draw.line([(left, top), (mid_x, mid_y)], fill=(255, 60, 60))
        draw.line([(right, top), (mid_x, mid_y)], fill=(255, 60, 60))
        
    elif app_lower == "whatsapp":
        # Draw a WhatsApp green chat bubble
        bubble_left = int(2 * scale)
        bubble_top = int(2 * scale)
        bubble_right = int(13 * scale)
        bubble_bottom = int(11 * scale)
        draw.ellipse([(bubble_left, bubble_top), (bubble_right, bubble_bottom)], fill=(34, 197, 94))
        
        tail_points = [
            (int(4 * scale), int(10 * scale)),
            (int(2 * scale), int(13 * scale)),
            (int(7 * scale), int(11 * scale))
        ]
        draw.polygon(tail_points, fill=(34, 197, 94))
        
        mid = size / 2.0
        draw.arc([(mid - 2*scale, mid - 2*scale), (mid + 2*scale, mid + 2*scale)], 180, 360, fill=(255, 255, 255), width=max(1, int(1.5*scale)))
        
    elif app_lower == "telegram":
        # Draw a paper airplane in a blue circle
        draw.ellipse([(int(1*scale), int(1*scale)), (int(14*scale), int(14*scale))], fill=(14, 165, 233))
        
        points = [
            (int(11 * scale), int(4 * scale)),
            (int(4 * scale), int(8 * scale)),
            (int(7 * scale), int(9 * scale))
        ]
        draw.polygon(points, fill=(255, 255, 255))
        points2 = [
            (int(11 * scale), int(4 * scale)),
            (int(7 * scale), int(9 * scale)),
            (int(9 * scale), int(11 * scale))
        ]
        draw.polygon(points2, fill=(224, 242, 254))
        
    else:
        # Generic yellow alert bell
        draw.ellipse([(int(5*scale), int(3*scale)), (int(10*scale), int(9*scale))], fill=(245, 158, 11))
        draw.rectangle([(int(3*scale), int(9*scale)), (int(12*scale), int(11*scale))], fill=(245, 158, 11))
        draw.ellipse([(int(7*scale), int(11*scale)), (int(8*scale), int(12*scale))], fill=(255, 255, 255))

    img.save(out_path)
    return out_path
