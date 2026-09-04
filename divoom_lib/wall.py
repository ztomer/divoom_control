#!/usr/bin/env python3
"""
wall.py — Multi-device display wall coordinator.
Splits images/animations into quadrants and streams them in parallel to multiple Divoom BLE screens.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from PIL import Image, ImageSequence
from typing import List, Dict, Any

from divoom_lib.divoom import Divoom
from divoom_lib.models import DeviceSlot

logger = logging.getLogger(__name__)


def wall_resolution(panel_resolution: int, grid_cols: int, grid_rows: int) -> tuple[int, int]:
    """Compute the **composite** wall canvas size from the per-panel resolution
    and the grid dimensions. This is the size of the source image you'd push
    to a wall (it gets split into per-panel slices).

     `panel_resolution` is the per-panel pixel dimension (16/32/64) — see
    `divoom_lib.models.capabilities.Capabilities.panel_resolution`. It is
    NOT the wall canvas size.

    Examples:
        # 2x2 wall of 16×16 panels (e.g. four Pixoos):
        wall_resolution(16, 2, 2)  # → (32, 32)
        # 2x1 wall of 32×32 panels (e.g. two TivooMax side-by-side):
        wall_resolution(32, 2, 1)  # → (64, 32)
        # 4x2 wall of 32×32 panels (e.g. eight Timoos):
        wall_resolution(32, 4, 2)  # → (128, 64)
    """
    if panel_resolution not in (16, 32, 64):
        raise ValueError(f"panel_resolution must be 16, 32, or 64; got {panel_resolution}")
    if grid_cols < 1 or grid_rows < 1:
        raise ValueError(f"grid must be at least 1×1; got {grid_cols}×{grid_rows}")
    return (panel_resolution * grid_cols, panel_resolution * grid_rows)

class DivoomWall:
    """
    Coordinates multiple Divoom screens arranged in a 2D grid to act as a single unified display.
    
    Usage::
    
        from divoom_lib.wall import DivoomWall
        
        # Configure devices in a 2x2 grid (each 16x16 pixels)
        configs = [
            {"mac": "AA:BB:CC:DD:EE:01", "x": 0, "y": 0, "size": 16}, # Top-left
            {"mac": "AA:BB:CC:DD:EE:02", "x": 1, "y": 0, "size": 16}, # Top-right
            {"mac": "AA:BB:CC:DD:EE:03", "x": 0, "y": 1, "size": 16}, # Bottom-left
            {"mac": "AA:BB:CC:DD:EE:04", "x": 1, "y": 1, "size": 16}  # Bottom-right
        ]
        
        wall = DivoomWall(configs)
        await wall.connect()
        await wall.show_image("large_animation.gif")
        await wall.disconnect()
    """
    def __init__(self, device_configs: List[Dict[str, Any]], custom_logger: logging.Logger | None = None) -> None:
        """
        Initializes the DivoomWall coordinator.
        
        Args:
            device_configs (list): Configuration for each screen in the display wall.
                                   Format: [{"mac": str, "x": int, "y": int, "size": int}]
        """
        self.logger = custom_logger or logger
        self.device_configs = device_configs
        self.devices: List[DeviceSlot] = []
        self.last_previews: Dict[str, bytes] = {}
        self.connect_results: Dict[str, Any] = {}   # P3: {mac: ConnectResult}
        
        # Calculate composite bounding box
        self.is_free_form = any("width" in config for config in self.device_configs)
        
        if self.is_free_form:
            self.min_x = min(config.get("x", 0) for config in self.device_configs)
            self.min_y = min(config.get("y", 0) for config in self.device_configs)
            max_x = max(config.get("x", 0) + config.get("width", 120) for config in self.device_configs)
            max_y = max(config.get("y", 0) + config.get("height", 120) for config in self.device_configs)
            
            self.total_width = max_x - self.min_x
            self.total_height = max_y - self.min_y
            self.grid_unit_size = self.device_configs[0].get("size", 16) if self.device_configs else 16
            
            for config in self.device_configs:
                mac = config["mac"]
                x = config.get("x", 0)
                y = config.get("y", 0)
                size = config.get("size", 16)
                width = config.get("width", 120)
                height = config.get("height", 120)
                
                divoom = Divoom(mac=mac, logger=self.logger, use_ios_le_protocol=True)
                # Store absolute bounding box: (divoom, x, y, size, width, height)
                self.devices.append(DeviceSlot(device=divoom, x=x, y=y, size=size, width=width, height=height))
        else:
            max_x_slot = 0
            max_y_slot = 0
            
            for config in self.device_configs:
                mac = config["mac"]
                x = config.get("x", 0)
                y = config.get("y", 0)
                size = config.get("size", 16)
                
                divoom = Divoom(mac=mac, logger=self.logger, use_ios_le_protocol=True)
                self.devices.append(DeviceSlot(device=divoom, x=x, y=y, size=size))
                
                if x + 1 > max_x_slot:
                    max_x_slot = x + 1
                if y + 1 > max_y_slot:
                    max_y_slot = y + 1
                    
            self.grid_unit_size = self.device_configs[0].get("size", 16) if self.device_configs else 16
            self.total_width = max_x_slot * self.grid_unit_size
            self.total_height = max_y_slot * self.grid_unit_size
            self.min_x = 0
            self.min_y = 0
            
        import json
        import hashlib
        config_str = json.dumps(self.device_configs, sort_keys=True)
        config_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()
        
        cache_dir = Path.home() / ".config" / "divoom-control" / "cache_wall"
        cache_dir.mkdir(parents=True, exist_ok=True)
        geom_file = cache_dir / "last_geometry.txt"
        
        geometry_changed = False
        if geom_file.exists():
            try:
                old_hash = geom_file.read_text().strip()
                if old_hash != config_hash:
                    geometry_changed = True
            except Exception:
                geometry_changed = True
        else:
            geometry_changed = True
            
        if geometry_changed:
            self.logger.info("Wall geometry changed. Purging wall cache...")
            for f in cache_dir.glob("*"):
                if f.is_file() and f.name != "last_geometry.txt":
                    try:
                        f.unlink()
                    except Exception:
                        pass
            try:
                geom_file.write_text(config_hash)
            except Exception:
                pass

        self.logger.info(f"Initialized DivoomWall (composite canvas size: {self.total_width}x{self.total_height} pixels)")

    async def connect(self) -> dict:
        """Connect every wall screen with BOUNDED concurrency + honest per-slot
        results (BLE Hardening P3). Instead of a bare ``gather`` connect-storm
        that fails opaquely, each slot is brought up via the retrying
        ``ensure_connected`` (serialized handshake, typed failure reason) so a
        partial wall reports WHICH screen failed and why. Returns the
        ``{mac: ConnectResult}`` map (also stored on ``self.connect_results``).
        Raises ``BleConnectionError`` only when EVERY slot fails — a partial
        wall stays usable for the screens that came up."""
        from divoom_lib.ble_connection import (
            connect_devices, BleConnectionError, WALL_CONNECT_CONCURRENCY,
        )
        self.logger.info("Connecting to all Divoom display wall devices...")
        items = [(slot.device.mac, slot.device) for slot in self.devices]
        results = await connect_devices(
            items, concurrency=WALL_CONNECT_CONCURRENCY,
            attempts=2, attempt_timeout=8.0,
        )
        self.connect_results = results
        ok = [m for m, r in results.items() if r.ok]
        bad = {m: r for m, r in results.items() if not r.ok}
        for mac, r in bad.items():
            self.logger.error("Wall slot %s failed to connect: %s (%s)",
                              mac, r.reason.value, r.detail)
        if not ok and results:
            # Total failure — surface the first slot's actionable reason.
            first = next(iter(results.values()))
            raise BleConnectionError(first)
        self.logger.info("Wall connected: %d/%d screens up.", len(ok), len(results))
        return results

    async def disconnect(self) -> None:
        """Disconnects all wall Divoom devices in parallel."""
        self.logger.info("Disconnecting from all Divoom display wall devices...")
        disconnect_tasks = []
        for slot in self.devices:
            disconnect_tasks.append(slot.device.disconnect())
        # return_exceptions=True: a bare gather re-raises on the FIRST failing slot
        # and abandons the rest, leaking those still-connected (and registry-held)
        # devices — which then blocks the next single↔wall switch. Disconnect ALL.
        results = await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        for slot, res in zip(self.devices, results):
            if isinstance(res, Exception):
                self.logger.warning("wall slot %s disconnect failed: %s",
                                    getattr(slot.device, "mac", "?"), res)
        self.logger.info("All display wall devices disconnected.")

    @property
    def is_connected(self) -> bool:
        """Returns True if all Divoom wall devices are connected."""
        return all(s.device.is_connected for s in self.devices)

    @property
    def is_alive(self) -> bool:
        """P2/P3 honest liveness — every slot genuinely alive (no pending drop),
        so the daemon's live-device cache doesn't hand back a half-dead wall."""
        return bool(self.devices) and all(
            getattr(s.device, "is_alive", getattr(s.device, "is_connected", False))
            for s in self.devices)

    async def show_image(self, file_path: str, time: int | None = None) -> bool:
        """
        Splits and displays a static image or animation on the unified display wall.
        Resizes the source image/GIF to the wall's composite resolution, cuts it into quadrants,
        and pushes each quadrant to the corresponding BLE screen.
        """
        if not Path(file_path).exists():
            self.logger.error(f"Image path not found: {file_path}")
            return False
            
        self.logger.info(f"Processing asset {file_path!r} for display wall...")
        
        # Resolve cache directory under ~/.config/divoom-control/cache_wall
        cache_dir = Path.home() / ".config" / "divoom-control" / "cache_wall"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        import hashlib
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
        except Exception:
            file_hash = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:16]
            
        main_img = Image.open(file_path)
        is_ani = hasattr(main_img, 'is_animated') and main_img.is_animated
        
        # Pair each task with its slot so result accounting can't drift out of
        # alignment with self.devices when a slot is skipped (see skipped_slots).
        display_tasks: list = []   # list of (slot, coro)
        skipped_slots: list = []   # slots that produced no push (counted as failures)

        # Perf: the full-canvas resize depends only on (source, total_w, total_h)
        # — it is IDENTICAL for every slot; only the per-slot crop differs. Compute
        # it ONCE, lazily, on the first cache miss (so the all-cached fast path
        # still does zero resizes). Without this, an N-device wall LIVE job — whose
        # content changes every tick, so the byte-hash cache misses every tick —
        # re-decoded+resized the whole canvas N times per tick (for a GIF: N × all
        # frames).
        resized_static = None          # PIL.Image for the static path
        resized_frames: list | None = None  # list[PIL.Image] for the animated path

        for slot in self.devices:
            divoom = slot.device
            x = slot.x
            y = slot.y
            size = slot.size
            width = slot.width
            height = slot.height
            
            if self.is_free_form:
                left = x - self.min_x
                upper = y - self.min_y
                right = left + width
                lower = upper + height
            else:
                left = x * size
                upper = y * size
                right = left + size
                lower = upper + size
            
            mac_clean = divoom.mac.replace(":", "_").replace("-", "_")
            ext = ".gif" if is_ani else ".png"
            cached_file_path = cache_dir / f"{file_hash}_{width}x{height}_{left}_{upper}_{right}_{lower}_{size}_{mac_clean}{ext}"
            temp_path_str = str(cached_file_path)
            
            if cached_file_path.exists():
                self.logger.info(f"Using cached wall split: {cached_file_path}")
            else:
                self.logger.info(f"Cropping slots bounding box: Left={left}, Upper={upper}, Right={right}, Lower={lower}")
                if is_ani:
                    # Resize every source frame to the full canvas ONCE (shared
                    # across slots); per slot we only crop (and, free-form, resize
                    # the crop to the panel).
                    if resized_frames is None:
                        resized_frames = [
                            f.resize((self.total_width, self.total_height), Image.NEAREST)
                            for f in ImageSequence.Iterator(main_img)
                        ]
                    frames = []
                    for resized_frame in resized_frames:
                        cropped_frame = resized_frame.crop((left, upper, right, lower))
                        if self.is_free_form:
                            cropped_frame = cropped_frame.resize((size, size), Image.NEAREST)
                        frames.append(cropped_frame)

                    if not frames:
                        # A truncated/corrupt GIF can report is_animated yet yield zero
                        # frames — frames[0] would IndexError and abort the WHOLE wall
                        # update (this loop isn't per-slot isolated). Skip this slot,
                        # but record it as a FAILURE: the screen got nothing, so the
                        # wall must NOT report overall success for it (and dropping
                        # the task silently would also misalign result indexing).
                        self.logger.warning("wall slot %s: animated source yielded 0 frames; skipping",
                                            getattr(divoom, "mac", "?"))
                        skipped_slots.append(slot)
                        continue
                    frames[0].save(
                        cached_file_path,
                        save_all=True,
                        append_images=frames[1:],
                        duration=main_img.info.get('duration', 100),
                        loop=main_img.info.get('loop', 0)
                    )
                else:
                    if resized_static is None:
                        resized_static = main_img.resize(
                            (self.total_width, self.total_height), Image.NEAREST)
                    cropped_img = resized_static.crop((left, upper, right, lower))
                    if self.is_free_form:
                        cropped_img = cropped_img.resize((size, size), Image.NEAREST)
                    cropped_img.save(cached_file_path)
            
            try:
                self.last_previews[slot.device.mac] = Path(temp_path_str).read_bytes()
            except Exception as ex:
                self.logger.warning(f"Failed to cache preview bytes for {slot.device.mac}: {ex}")
                
            display_tasks.append((slot, self._push_slot(divoom, temp_path_str, time)))

        # Execute all BLE streams concurrently
        self.logger.info(f"Streaming splits concurrently to {len(display_tasks)} screens...")
        results = await asyncio.gather(*[t for _, t in display_tasks], return_exceptions=True)

        # Check results. Each result is paired with its own slot, so a skipped
        # slot earlier in the loop can't shift this mapping.
        all_ok = not skipped_slots   # any skipped slot -> wall did not fully render
        for (slot, _), res in zip(display_tasks, results):
            if isinstance(res, Exception):
                self.logger.error(f"Failed to display slot ({slot.x}, {slot.y}) on device {slot.device.mac}: {res}")
                all_ok = False
            elif not res:
                self.logger.error(f"Failed to display slot ({slot.x}, {slot.y}) on device {slot.device.mac}")
                all_ok = False

        return all_ok
            
    async def _push_slot(self, divoom, path: str, time: int | None) -> bool:
        """BLE Hardening P3 self-heal: revive a dropped slot via Phase 1's
        bounded reconnect BEFORE pushing, so one screen's transient drop doesn't
        freeze its content while the rest keep updating. A genuinely dead slot
        raises (captured per-slot by ``show_image``'s ``return_exceptions``)."""
        alive = getattr(divoom, "is_alive", getattr(divoom, "is_connected", False))
        if not alive:
            from divoom_lib.ble_connection import ensure_connected, BleConnectionError
            self.logger.warning("Wall slot %s not alive — reconnecting before push", divoom.mac)
            res = await ensure_connected(divoom, attempts=2, attempt_timeout=8.0)
            if not res.ok:
                raise BleConnectionError(res)
        return await divoom.display.show_image(path, time=time)

    async def set_light(self, color: str, brightness: int = 100) -> bool:
        """Sets a unified solid light color across all screens in the wall."""
        self.logger.info(f"Setting solid light {color} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_light(color=color, brightness=brightness))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def show_clock(self, clock: int = 0) -> bool:
        """Displays clock style on all screens in the wall."""
        self.logger.info(f"Displaying clock style {clock} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_clock(clock=clock))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def show_effects(self, number: int = 0) -> bool:
        """Displays VJ effect style on all screens in the wall."""
        self.logger.info(f"Displaying VJ effect {number} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_effects(number=number))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def show_visualization(self, number: int = 0) -> bool:
        """Displays visualization EQ style on all screens in the wall."""
        self.logger.info(f"Displaying visualization EQ {number} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_visualization(number=number))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def set_brightness(self, brightness: int) -> bool:
        """Sets brightness across all screens (LAN transport when available,
        else BLE), matching the GUI's per-device transport choice."""
        self.logger.info(f"Setting brightness {brightness} across all screens...")
        tasks = []
        for slot in self.devices:
            if getattr(slot.device, "lan", None):
                tasks.append(slot.device.lan.set_brightness(brightness))
            else:
                tasks.append(slot.device.device.set_brightness(brightness))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True or isinstance(res, dict) for res in results)

    async def set_volume(self, volume: int) -> bool:
        """Sets volume across all screens in the wall."""
        self.logger.info(f"Setting volume {volume} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.music.set_volume(volume))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def switch_channel(self, channel: str) -> bool:
        """Switches all screens in the wall to the same channel."""
        self.logger.info(f"Switching all screens to channel {channel}...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.switch_channel(channel))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True or isinstance(res, dict) for res in results)

    async def push_text(self, text: str, color: str = "#FFFFFF", font_size: int = 1,
                        speed: int = 50, effect_style: int = 1) -> bool:
        """Pushes the same scrolling text to every screen, using each screen's
        own pixel size for the display box (the LPWA 0x87 sequence)."""
        from divoom_lib.models import (
            LPWA_CONTROL_DISPLAY_BOX, LPWA_CONTROL_FONT, LPWA_CONTROL_COLOR,
            LPWA_CONTROL_SPEED, LPWA_CONTROL_EFFECTS, LPWA_CONTROL_CONTENT,
        )
        self.logger.info(f"Pushing text {text!r} across all screens...")

        async def _push(divoom, size: int) -> bool:
            t = divoom.text
            box = 0
            await t.set_light_phone_word_attr(LPWA_CONTROL_DISPLAY_BOX, x=0, y=0,
                                              width=size, height=size, text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_FONT, font_size=int(font_size), text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_COLOR, color=color, text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_SPEED, speed=int(speed), text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_EFFECTS, effect_style=int(effect_style))
            res = await t.set_light_phone_word_attr(LPWA_CONTROL_CONTENT, text_content=str(text), text_box_id=box)
            return res is not False

        results = []
        for slot in self.devices:
            divoom = slot.device
            sz = slot.size
            results.append(await _push(divoom, int(sz)))
        return all(results)

    def get_last_previews(self) -> dict:
        """Return base64 Data URLs of the last images/GIFs pushed to the slots."""
        import base64
        res = {}
        for mac, data in self.last_previews.items():
            if not data:
                continue
            mime = "image/gif" if data.startswith(b"GIF8") else "image/png"
            res[mac] = f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"
        return res
