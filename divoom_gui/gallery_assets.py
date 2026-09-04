"""Gallery previews, cached — but fetched and DECODED by the daemon.

R70 P2.2. Replaces `gallery_download.py`, which downloaded from
`fin.divoom-gz.com` itself and ran `divoom_lib.media_decoder` in the GUI
process.

**This is not only a relocation; it fixes decoding.** The GUI's decoder handled
magic-43, raw GIF/PNG/JPEG and a generic fallback. The daemon's
`media::resolve_to_gif` handles all of those PLUS magic 9 (AES), 18/26
(AES + LZO, tiled) and 0xAA hot files, re-encoding each to an animated GIF.
Gallery items in those container formats were exactly the ones the GUI rendered
as empty tiles.

**What is cached here, and why that is still legitimate.** The disk cache holds
the daemon's ANSWERS — the decoded image bytes it returned — so a second open
of the gallery does not re-download. Caching a reply is not a second
implementation; nothing here inspects a Divoom container, sniffs a magic byte,
or decides how to decode. The mime type comes from the daemon's own data-url.

**The one-time purge.** Old caches contain `.bin` intermediates written by the
GUI's decoder, and previews that decoder produced — including the blank ones
R64 added an `is_black_image` recovery pass for. That recovery existed to work
around a decoder being deleted here, so it is deleted with it, and the cache is
cleared once instead. The first gallery open after upgrading re-fetches; every
later one is served from disk.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger("divoom_gui")

#: Bumped when the cache's provenance changes. The suffix is the R70 migration:
#: everything written by the GUI-side decoder is discarded once.
CACHE_STAMP = ".provenance-r70-daemon"

_MIME_EXT = {
    "image/gif": ".gif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
_EXT_MIME = {v: k for k, v in _MIME_EXT.items()}


def ensure_cache_dir(cache_dir: Path) -> Path:
    """Create the cache dir, purging a pre-R70 one exactly once."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = cache_dir / CACHE_STAMP
    if stamp.exists():
        return cache_dir
    removed = 0
    for path in cache_dir.iterdir():
        if path.is_file() and path.name != CACHE_STAMP:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        logger.info(
            "Gallery cache: cleared %d file(s) written by the old in-GUI decoder; "
            "previews will be re-fetched from the background service.", removed)
    try:
        stamp.write_text("previews come from divoomd (R70 P2.2)\n", encoding="utf-8")
    except OSError:
        pass
    return cache_dir


def cached_preview(cache_dir: Path, file_id: str) -> str:
    """A `data:` URL from disk, or `""`.

    The extension names the mime type — the same mapping the daemon used when
    it produced the bytes. No sniffing, no decoding.
    """
    stem = cache_dir / file_id.replace("/", "_")
    for ext, mime in _EXT_MIME.items():
        path = stem.with_suffix(ext)
        if path.exists() and path.stat().st_size > 0:
            try:
                return f"data:{mime};base64," + base64.b64encode(
                    path.read_bytes()).decode("ascii")
            except OSError as exc:
                logger.warning("gallery cache read failed for %s: %s", path.name, exc)
    return ""


def _store(cache_dir: Path, file_id: str, data_url: str) -> None:
    """Write the daemon's bytes to disk under the extension it named."""
    try:
        header, b64 = data_url.split(",", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0]
    except (ValueError, IndexError):
        logger.warning("gallery: daemon returned a malformed data url for %s", file_id)
        return
    ext = _MIME_EXT.get(mime)
    if ext is None:
        # An unknown mime is not something to guess at: serve it this session
        # and do not persist a file whose type we cannot name.
        logger.info("gallery: not caching %s (unhandled mime %s)", file_id, mime)
        return
    try:
        (cache_dir / file_id.replace("/", "_")).with_suffix(ext).write_bytes(
            base64.b64decode(b64))
    except (OSError, ValueError) as exc:
        logger.warning("gallery: could not cache %s: %s", file_id, exc)


def preview_for(client, cache_dir: Path, file_id: str) -> str:
    """The preview for one gallery asset: disk first, then the daemon.

    Returns `""` when the asset cannot be decoded — an empty tile is correct
    there, because there is genuinely nothing to show. The REASON is logged
    rather than raised: one undecodable item must not empty the whole gallery,
    which is a different failure from the cloud being unreachable (that one is
    reported by the caller, from `fetch_gallery` itself).
    """
    if not file_id:
        return ""
    hit = cached_preview(cache_dir, file_id)
    if hit:
        return hit
    from divoom_client.daemon_cloud import CloudUnavailable

    try:
        data_url = client.get_animated_preview(file_id)
    except CloudUnavailable as exc:
        logger.warning("gallery preview %s unavailable (%s): %s",
                       file_id, exc.cause, exc.reason)
        return ""
    if not data_url:
        return ""
    _store(cache_dir, file_id, data_url)
    return data_url
