# gui/gallery_hot_api.py — hot-channel + custom-art RPC wrappers and the
# animated-preview download/decode path. Split from gallery_sync.py
# (500-LOC rule); mixed into GallerySyncMixin.

import json
import logging
import base64
import threading
import time
from pathlib import Path


logger = logging.getLogger("divoom_gui")


class GalleryHotApiMixin:
    def custom_art_push(self, payload_json: str, page: int,
                        slot: int | None = None) -> str:
        """Push cloud files to a custom art page on the device. JSON summary.

        ``payload_json`` is either a {slot: file_id} mapping (preferred — the
        page is sent once, unmapped slots cleared) or a legacy file-id list."""
        logger.info(f"GUI Action: Custom art push page={page} slot={slot} payload={payload_json}")
        client = self._client()
        if client is None:
            return json.dumps({"success": False, "error": "no daemon available"})
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            return json.dumps({"success": False, "error": "invalid payload"})
        if isinstance(payload, dict):
            return json.dumps(client.custom_art_push([], int(page), slots=payload))
        return json.dumps(client.custom_art_push(payload, int(page), slot))

    def custom_art_query_page(self, page: int = 0) -> str:
        """Query device for filled slot IDs on a custom art page. JSON summary."""
        logger.info(f"GUI Action: Custom art query page={page}")
        client = self._client()
        if client is None:
            return json.dumps({"success": False, "error": "no daemon available"})
        return json.dumps(client.custom_art_query_page(page))

    def hot_channel_update(self) -> str:
        """Start HOT channel update in background on daemon. Returns immediately."""
        logger.info("GUI Action: Hot channel update (start)...")
        client = self._client()
        if client is None:
            return json.dumps({"success": False, "error": "no daemon available"})
        size = self._active_device_size() if hasattr(self, "_active_device_size") else 16
        # R53: pass the active device address so the DAEMON stamps the
        # last-checked state under the same key the GUI reads by (hot_get_check).
        addr = self._active_device_mac() if hasattr(self, "_active_device_mac") else None
        r = client.hot_update(device_size=int(size), show=True, address=addr or "")
        return json.dumps(r)

    def sync_now(self) -> str:
        """Manually run Auto-Sync immediately, instead of waiting for the
        scheduled interval. Pushes hot-channel content to every toggled sync
        target (`hotchannel_config.get_targets()` — the same list the
        Routines > Auto-Sync device toggles edit) one at a time — the daemon
        owns a single active device, so this connects, runs the same
        `hot_update` the "Update Hot Channel" button uses, waits for it to
        finish, disconnects (implicitly, on the next `connect_single_device`),
        and moves on. A device that can't connect or fails to sync is
        reported and skipped, not fatal to the run (mirrors
        `monthly_best_daemon.py::_push_items_to_target`'s per-address
        try/except). Runs in a background thread; returns immediately."""
        logger.info("GUI Action: Sync Now (start)...")
        from divoom_lib import hotchannel_config

        def notify(address, phase, **extra):
            if not self.window:
                return
            try:
                payload = {"address": address, "phase": phase, **extra}
                js = f"if (window.onSyncNowProgress) {{ window.onSyncNowProgress({json.dumps(payload)}); }}"
                self.window.evaluate_js(js)
            except Exception as e:
                logger.warning(f"Failed to send sync-now progress: {e}")

        def worker():
            targets = hotchannel_config.get_targets()
            summary = {"total": len(targets), "ok": 0, "failed": 0}
            for address in targets:
                notify(address, "connecting")
                try:
                    if not self.connect_single_device(address):
                        summary["failed"] += 1
                        notify(address, "error", error="Could not connect")
                        continue
                except Exception as e:
                    summary["failed"] += 1
                    notify(address, "error", error=str(e))
                    continue

                try:
                    client = self._client()
                    if client is None:
                        raise RuntimeError("no daemon available")
                    size = self._active_device_size() if hasattr(self, "_active_device_size") else 16
                    start = client.hot_update(device_size=int(size), show=True, address=address)
                    if not start.get("success"):
                        raise RuntimeError(start.get("error") or "could not start hot update")
                    notify(address, "syncing")

                    status = {"phase": "starting"}
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        status = client.hot_update_progress()
                        if status.get("phase") in ("done", "error"):
                            break
                        time.sleep(0.6)

                    if status.get("phase") == "done":
                        summary["ok"] += 1
                        served = len((status.get("result") or {}).get("served", []))
                        notify(address, "done", served=served)
                    else:
                        summary["failed"] += 1
                        notify(address, "error", error=status.get("error") or "timed out")
                except Exception as e:
                    summary["failed"] += 1
                    notify(address, "error", error=str(e))

            if self.window:
                try:
                    js = f"if (window.onSyncNowComplete) {{ window.onSyncNowComplete({json.dumps(summary)}); }}"
                    self.window.evaluate_js(js)
                except Exception as e:
                    logger.warning(f"Failed to send sync-now completion: {e}")

        threading.Thread(target=worker, name="DivoomSyncNow", daemon=True).start()
        return json.dumps({"success": True})

    def hot_update_status(self) -> str:
        """Query daemon for current hot update progress."""
        logger.debug("GUI Action: Hot update status poll...")
        client = self._client()
        if client is None:
            return json.dumps({"phase": "error", "error": "no daemon"})
        return json.dumps(client.hot_update_progress())

    def hot_get_check(self, address: str = "") -> str:
        """R53: the daemon-recorded last hot-channel check for a device (or
        ``{}``). Reads the shared ``hot_update_state.json`` the daemon writes.
        With no ``address`` it resolves the active device — the same key
        ``hot_channel_update`` passes for the write, so read and write always
        agree."""
        from divoom_lib import hot_update_state
        addr = address or (self._active_device_mac()
                           if hasattr(self, "_active_device_mac") else "")
        return json.dumps(hot_update_state.get_check(addr or ""))

    def hot_update_preview(self) -> str:
        """Fetch the hot channel manifest from Divoom's cloud and cross-reference
        with the cached gallery to show what would be pushed."""
        try:
            client = self._client()
            if client is None:
                raise RuntimeError("the background service is not running")
            size = self._active_device_size() if hasattr(self, "_active_device_size") else 16
            # R70 P2.3: the manifest comes from the daemon, which owns the
            # size -> DeviceType mapping and the manifest cache. The GUI used
            # to hit the same endpoint itself, with a second copy of the
            # mapping and no visibility of that cache.
            files = client.hot_manifest(int(size))

            cache_file = Path.home() / ".config" / "divoom-control" / "gallery_cache.json"
            name_map = {}
            if cache_file.exists():
                try:
                    cached = json.loads(cache_file.read_text(encoding="utf-8"))
                    for item in cached:
                        fid = item.get("file_id")
                        if fid:
                            name_map[fid] = {
                                "name": item.get("name", "unnamed"),
                                "likes": item.get("likes", 0),
                                "preview_url": item.get("preview_url", ""),
                            }
                except Exception:
                    pass

            items = []
            for f in files:
                file_id = f.get("file_id", "")
                meta = name_map.get(file_id, {})
                # Don't send raw CDN URL as preview — it's a binary container the
                # browser can't render. Animated previews are loaded lazily via
                # get_animated_preview() which handles download+decode.
                items.append({
                    "file_id": file_id,
                    "version": f.get("version", 0),
                    "vendor_id": f.get("vendor_id", 0),
                    "name": meta.get("name") or file_id.rsplit("/", 1)[-1],
                    "likes": meta.get("likes", 0),
                    "preview_url": meta.get("preview_url", ""),
                    "has_cache": file_id in name_map,
                })

            # Show newest-first deterministically. The hot API's list order is
            # not a stable contract (it can reorder its "featured" set between
            # requests), which made the newest file land at an arbitrary tile —
            # so the just-added art wasn't where the user looked for it. Sorting by
            # version here pins the newest to tile 0 regardless of API order.
            items.sort(key=lambda it: it.get("version", 0), reverse=True)

            return json.dumps({"success": True, "items": items, "count": len(items)})
        except Exception as e:
            logger.warning(f"hot_update_preview failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    def get_animated_preview(self, file_id: str) -> str:
        """A `data:` URL for one gallery or hot-channel asset.

        R70 P2.3. This was ~90 lines of download-and-decode in the GUI process:
        urllib to the CDN, magic-43 extraction, raw GIF/PNG/JPEG sniffing, a
        cloud-container decoder, a PIL resize of every frame into an animated
        GIF, and a PIL catch-all. `divoomd` has answered the identical command
        the whole time — `sync_artwork.rs` names THIS METHOD as the thing it was
        written for parity with — and nothing ever called it, so both halves
        lived side by side.

        The daemon's decoder is the larger one: magic 9 (AES), 18/26 (AES+LZO,
        tiled) and 0xAA hot files, plus everything the copy here handled.
        """
        from divoom_gui import gallery_assets

        logger.info(f"GUI Action: Fetching animated preview for {file_id}")
        client = self._client()
        if client is None:
            logger.warning("no daemon: cannot fetch preview for %s", file_id)
            return ""
        cache_dir = gallery_assets.ensure_cache_dir(
            Path.home() / ".config" / "divoom-control" / "cache_gallery")
        return gallery_assets.preview_for(client, cache_dir, file_id)

    @staticmethod
    def _coerce_list(args, kwargs, key) -> list:
        if len(args) == 1:
            v = args[0]
            if isinstance(v, str):
                try:
                    parsed = json.loads(v)
                    return parsed if isinstance(parsed, list) else [parsed]
                except ValueError:
                    return [v]
            return list(v) if isinstance(v, (list, tuple)) else [v]
        if len(args) > 1:
            return list(args)
        if key in kwargs and isinstance(kwargs[key], (list, tuple)):
            return list(kwargs[key])
        return []

    @staticmethod
    def _coerce_dict(args, kwargs) -> dict:
        if len(args) == 1:
            v = args[0]
            if isinstance(v, str):
                try:
                    parsed = json.loads(v)
                    return parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    return {}
            return dict(v) if isinstance(v, dict) else {}
        allowed = ("enabled", "interval", "classify", "targets")
        return {k: kwargs[k] for k in allowed if k in kwargs}
