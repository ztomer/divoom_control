#!/usr/bin/env python3
"""Prove no gallery asset renders blank — through the DAEMON's decoder.

**Why this was rewritten (R72 P3.1).** The previous version said it "mirrors the
exact decode chain the GUI uses" and that "media_decoder is the single source of
truth that feeds the UI". Both were true when it was written. Neither survived
**R70 P2.3**, which moved gallery decode into the daemon precisely because the
daemon could decode magic 9 (AES), 18/26 (AES+LZO, tiled) and 0xAA hot files
that the GUI copy never could.

So this harness had become misleading in BOTH directions: it would pass on
assets the product cannot render, and fail on containers the product handles
fine. A green run said nothing about what a user sees — worse than no harness,
because it looked like one.

It was also a full parallel implementation of three things the daemon owns —
its own `divoom_auth` login, its own `urllib` POST to `appin.divoom-gz.com`, and
its own `media_decoder` — i.e. exactly what R70 spent a round removing from the
GUI. It survived only because no gate in this repo had ever scanned `scripts/`.
The capability census (R72 P0) found it on its first run.

Now it asks the daemon for the file list and for each decoded preview, and
checks THOSE bytes. What it verifies is what ships.

    scripts/verify_gallery_render.py                # every category
    scripts/verify_gallery_render.py --cats 18,0,3  # a few
    scripts/verify_gallery_render.py --limit 5      # fewer per category

**Start the daemon yourself** — this refuses to spawn one, for the same reason
`hw_verify.py` does: a shell-launched daemon has no Bluetooth TCC grant. It also
needs a configured Divoom account, since the file list is a cloud call.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import io as _io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from _tui import err, hr, info, ok, section, warn  # noqa: E402

from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH, DaemonClient  # noqa: E402

# The classify ids the gallery browser offers, in the order it shows them.
CLASSIFY = [18, 0, 3, 17, 4, 8, 9, 6, 5, 15, 7, 16, 1, 40, 12, 19]


def is_blank(img) -> bool:
    """Fully transparent, or a single flat colour, counts as blank.

    Kept verbatim in spirit from the previous version -- this predicate is the
    part that had value. A dark image is NOT blank; a one-colour image is.
    """
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        lo, hi = alpha.getextrema()
        if lo == 0 and hi == 0:
            return True
    extrema = img.convert("RGB").getextrema()
    return all(lo == hi for lo, hi in extrema)


def decode_data_url(data_url: str):
    """`data:image/gif;base64,...` -> a PIL image, or None if it is not one."""
    from PIL import Image

    if not isinstance(data_url, str) or "," not in data_url:
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    try:
        return Image.open(_io.BytesIO(raw))
    except Exception:
        return None


def require_daemon(socket_path: str) -> DaemonClient:
    client = DaemonClient(socket_path)
    reason = ""
    try:
        st = client.device_status()
        if isinstance(st, dict) and (st.get("unreachable") or st.get("success") is False):
            reason = str(st.get("error") or st)
    except Exception as exc:
        reason = str(exc)
    if reason:
        err(f"no daemon on {socket_path} ({reason})")
        info("This script does not start one: a shell-launched daemon has no")
        info("Bluetooth TCC grant and dies on its first scan. Launch the GUI.")
        raise SystemExit(2)
    return client


def check_category(client, classify: int, limit: int) -> tuple[int, int, list[str]]:
    """(checked, blank, notes) for one category."""
    try:
        items = client.get_category_file_list(classify, limit=limit)
    except Exception as exc:
        return 0, 0, [f"file list failed: {exc}"]
    if not isinstance(items, list):
        return 0, 0, [f"unexpected file-list reply: {items!r}"]

    checked = blank = 0
    notes: list[str] = []
    for item in items:
        file_id = (item or {}).get("FileId") if isinstance(item, dict) else None
        if not file_id:
            continue
        try:
            url = client.get_animated_preview(str(file_id))
        except Exception as exc:
            notes.append(f"{file_id}: preview failed: {exc}")
            continue
        img = decode_data_url(url)
        if img is None:
            notes.append(f"{file_id}: the daemon returned no decodable image")
            blank += 1
            checked += 1
            continue
        checked += 1
        if is_blank(img):
            blank += 1
            notes.append(f"{file_id}: renders BLANK")
    return checked, blank, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    ap.add_argument("--cats", default="", help="comma-separated classify ids")
    ap.add_argument("--limit", type=int, default=20, help="files per category")
    args = ap.parse_args()

    cats = [int(c) for c in args.cats.split(",") if c.strip()] or CLASSIFY
    client = require_daemon(args.socket)

    section(f"gallery render check — {len(cats)} categor(ies), "
            f"{args.limit} file(s) each, via the daemon's decoder")

    total = total_blank = 0
    for classify in cats:
        checked, blank, notes = check_category(client, classify, args.limit)
        total += checked
        total_blank += blank
        line = f"classify {classify:<3} {checked:>3} checked, {blank} blank"
        (err if blank else ok)(line)
        for n in notes[:5]:
            info(f"    {n}")
        if len(notes) > 5:
            info(f"    (+{len(notes) - 5} more)")

    hr()
    if not total:
        warn("nothing was checked — is the account configured?")
        return 1
    (err if total_blank else ok)(
        f"{total} asset(s) checked, {total_blank} blank")
    return 1 if total_blank else 0


if __name__ == "__main__":
    sys.exit(main())
