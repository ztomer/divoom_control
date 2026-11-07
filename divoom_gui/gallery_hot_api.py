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
    def custom_art_push(self, mac: str, payload_json: str, page: int, slot: int | None = None) -> str:
        """Push cloud files to a custom art page on the panel ``mac`` names.
        JSON summary.

        ``payload_json`` is either a {slot: file_id} mapping (preferred — the
        page is sent once, unmapped slots cleared) or a legacy file-id list.
        P5.7: it named no panel, so the daemon pushed the page to whichever one
        it had selected when the request arrived."""
        logger.info(f"GUI Action: Custom art push to {mac} page={page} slot={slot} payload={payload_json}")
        if not mac or mac == "MatrixWall":
            return json.dumps({"success": False, "error": "custom art is pushed to one panel; name it"})
        client = self._client()
        if client is None:
            return json.dumps({"success": False, "error": "no daemon available"})
        try:
            payload = json.loads(payload_json)
        except TypeError, ValueError:
            return json.dumps({"success": False, "error": "invalid payload"})
        if isinstance(payload, dict):
            return json.dumps(client.custom_art_push([], int(page), slots=payload, mac=mac))
        return json.dumps(client.custom_art_push(payload, int(page), slot, mac=mac))

    def hot_channel_update(self, mac: str) -> str:
        """Start the HOT channel update on the panel ``mac`` names, in the
        daemon's background. Returns immediately.

        The daemon records the run's verdict under that panel when it ends,
        failed or not (U.5; read back by `hot_verdict`)."""
        logger.info(f"GUI Action: Hot channel update on {mac} (start)...")
        if not mac or mac == "MatrixWall":
            return json.dumps({"success": False, "error": "the hot channel updates one panel; name it"})
        client = self._client()
        if client is None:
            return json.dumps({"success": False, "error": "no daemon available"})
        r = client.hot_update(device_size=int(self._size_of(mac)), show=True, address=mac, by="button")
        return json.dumps(r)

    def sync_now(self) -> str:
        """Run Auto-Sync's hot-channel update now, on every panel the app's
        settings register (`settings_devices.registered_devices()` -- the
        table the Auto-Sync rows edit), one after another. Runs in a thread;
        returns immediately.

        Each panel's run is the daemon's `hot_update` with ``by="sync_now"``,
        and the DAEMON records its verdict, failures included -- a panel that
        is not linked is a recorded failure, the line the row then shows (U.5).
        It used to connect each panel first, through the GUI's own connect
        click (which also re-wrote the app's "last connected" panel), and to
        report into rows that kept nothing: the panel's link is the fleet's
        (D.DV2c), and the verdict is the daemon's record."""
        logger.info("GUI Action: Sync Now (start)...")
        from divoom_lib import settings_devices

        def notify(address, phase, **extra):
            if not self.window:
                return
            try:
                payload = {"address": address, "phase": phase, **extra}
                js = f"if (window.onSyncNowProgress) {{ window.onSyncNowProgress({json.dumps(payload)}); }}"
                self.window.evaluate_js(js)
            except Exception as e:
                logger.warning(f"Failed to send sync-now progress: {e}")

        def wait_idle(client, deadline):
            status = {"phase": "starting"}
            while time.monotonic() < deadline:
                status = client.hot_update_progress()
                if status.get("phase") not in ("starting", "fetching_manifest", "downloading", "uploading"):
                    return status
                time.sleep(0.6)
            return status

        def worker():
            targets = [addr for addr, _ in settings_devices.registered_devices()]
            for index, address in enumerate(targets, start=1):
                notify(address, "checking", index=index, total=len(targets))
                try:
                    client = self._client()
                    if client is None:
                        raise RuntimeError("no daemon available")
                    # One update at a time on the daemon: wait out one already
                    # running (a button press) rather than be refused.
                    wait_idle(client, time.monotonic() + 120)
                    start = client.hot_update(
                        device_size=int(self._size_of(address)), show=True, address=address, by="sync_now"
                    )
                    if start.get("success"):
                        wait_idle(client, time.monotonic() + 120)
                except Exception as e:
                    logger.warning(f"Sync Now on {address} failed: {e}")
                # The row shows the daemon's record: re-read it now.
                notify(address, "finished")

            if self.window:
                try:
                    js = f"if (window.onSyncNowComplete) {{ window.onSyncNowComplete({json.dumps({'total': len(targets)})}); }}"
                    self.window.evaluate_js(js)
                except Exception as e:
                    logger.warning(f"Failed to send sync-now completion: {e}")

        threading.Thread(target=worker, name="DivoomSyncNow", daemon=True).start()
        return json.dumps({"success": True})

    def hot_verdict(self, address: str) -> str:
        """U.5: the hot-channel verdict the daemon recorded for the panel
        ``address`` names (or ``{}``) -- the newest run by any path."""
        from divoom_lib import hot_verdict

        return json.dumps(hot_verdict.get(address or ""))

    def hot_verdicts(self) -> str:
        """U.5: every panel's hot-channel verdict, ``{panel id: entry}`` -- the
        Auto-Sync rows' shorter form of the same record."""
        from divoom_lib import hot_verdict

        return json.dumps(hot_verdict.all_verdicts())

    def hot_update_preview(self, mac: str) -> str:
        """Fetch the hot channel manifest from Divoom's cloud for the panel
        ``mac`` names (its size picks the manifest) and cross-reference with
        the cached gallery to show what would be pushed."""
        try:
            client = self._client()
            if client is None:
                raise RuntimeError("the background service is not running")
            size = self._size_of(mac or None)
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
                items.append(
                    {
                        "file_id": file_id,
                        "version": f.get("version", 0),
                        "vendor_id": f.get("vendor_id", 0),
                        "name": meta.get("name") or file_id.rsplit("/", 1)[-1],
                        "likes": meta.get("likes", 0),
                        "preview_url": meta.get("preview_url", ""),
                        "has_cache": file_id in name_map,
                    }
                )

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
        cache_dir = gallery_assets.ensure_cache_dir(Path.home() / ".config" / "divoom-control" / "cache_gallery")
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
