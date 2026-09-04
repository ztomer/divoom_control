# divoom_lib/models/capabilities.py
# R13 §1 — device capability detection.
#
# Source of truth (per docs/ENGINEERING_NOTES.md):
# - decompiled APK: references/apk/decompiled_src/.../DeviceFunction.java:540-580
#   (DeviceTypeEnum) + SppProc$CMD_TYPE.java (which commands exist).
# - common knowledge about which models have which hardware (FM, SD slot,
#   scoreboard widget). Conservative — a capability is asserted only when
#   the device class is known to support it. Unknown device types get the
#   Pixoo (most limited) baseline.
#
# Wire-level: this is a static table. The lib doesn't query the device for
# its capabilities — the protocol has no "what features do you have?"
# command. If a future command is added, the table can be filled from a
# device query instead.
#
# Identifier hierarchy (R13 review — name heuristic removed, hardware-derived
# paths preferred):
#
#   1. Explicit ``device_type`` kwarg — caller knows the model.
#   2. ``DeviceRegistry`` — per-install MAC → device_type, saved to
#      ``~/.config/divoom-control/devices.json``. The user pairs each
#      device once; the lib remembers it forever.
#   3. ``capabilities_from_manufacturer_data`` — bleak's
#      ``AdvertisementData.manufacturer_data`` (BLE ad packet, hardware-
#      derived, no connection needed). The fingerprint table is
#      intentionally small; populate it as the user identifies new
#      devices.
#   4. Baseline (most-limited Pixoo defaults) — always available.

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Capabilities:
    """What a specific Divoom device class can do. Immutable.

    `panel_resolution` is the **per-panel** pixel size in one dimension
    (16 / 32 / 64). All Divoom panels are square, so a 16×16 device has
    `panel_resolution=16`, a 32×32 has 32, a 64×64 has 64. The image
    pipeline resizes to `panel_resolution × panel_resolution` BEFORE
    encoding (see `docs/ENGINEERING_NOTES.md` invariant 1).

     `panel_resolution` is **NOT** the wall composite size. For a virtual
    wall of N columns × M rows, the composite canvas is
    `panel_resolution * N` × `panel_resolution * M` — compute that
    separately (see `wall_resolution` in `divoom_lib/wall.py`).
    """
    panel_resolution: int                  # 16 / 32 / 64 (per-panel pixels, square)
    has_fm: bool                          # FM radio chip
    has_sd: bool                          # SD card slot for music
    has_lightning: bool                   # 0x45 channel 0x01 (light effects)
    has_scoreboard: bool                  # 0x45 channel 0x06 (sports scoreboard)
    has_anim_8b: bool                     # 0x8B 3-phase animation streaming
    has_orientation: bool                 # 0xBD 0x23 (rotate display)
    has_screen_mirror: bool               # 0xBD 0x24 (mirror display)
    has_factory_reset: bool               # 0xBD 0x25 (factory reset)
    has_alarm: bool                       # 0x42 / 0x43 (alarms)
    has_sleep: bool                       # 0x40 / 0x41 (sleep aid)
    has_weather: bool                     # 0x5D / 0x5E (weather widget)
    has_low_power: bool                   # 0xB2 / 0xB3 (low power mode)
    has_24h_clock: bool                   # 0x2C (12/24h clock)
    has_temp_unit: bool                   # 0x2B (°C/°F)
    has_mic: bool                         # device has a microphone
    notes: tuple[str, ...] = field(default_factory=tuple)


# ── Conservative baseline (unknown device types) ───────────────────────────
# Use the most-limited real device as the default. If a future device query
# returns a different type, replace the capabilities.

BASELINE = Capabilities(
    panel_resolution=16,
    has_fm=False,
    has_sd=False,
    has_lightning=True,
    has_scoreboard=False,
    has_anim_8b=True,
    has_orientation=False,
    has_screen_mirror=False,
    has_factory_reset=False,
    has_alarm=True,
    has_sleep=True,
    has_weather=True,
    has_low_power=True,
    has_24h_clock=True,
    has_temp_unit=True,
    has_mic=False,
    notes=("Default baseline; device type not recognised — assume most-limited.",),
)


# ── Per-device-type table ──────────────────────────────────────────────────
# Keys = APK DeviceTypeEnum name (DeviceFunction.java:546+).
# Verified against the user's 4 devices:
#   Pixoo-1   → "Pixoo"
#   Tivoo-Max → "TivooMax"
#   Ditoo     → "DITOO"
#   Timoo     → "TIMOO"

DEVICE_CAPABILITIES: dict[str, Capabilities] = {
    # 16×16 baseline devices
    "TIMEBOX_NORMAL": replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=False, has_screen_mirror=False, has_factory_reset=False, has_mic=False, notes=("Original Timebox; very limited.",)),
    "TIMEBOX_MIN":    replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=False, has_screen_mirror=False, has_factory_reset=False, has_mic=False, notes=("Timebox Mini.",)),
    "Pixoo":          replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Original Pixoo (1st gen, 16×16).",)),
    "Pixoo_SlingBag": replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixoo Sling Bag variant.",)),
    "PixoolNull":     replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixoo 16 null variant.",)),
    "Pixoo16Wifi":    replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixoo 16 WiFi.",)),
    "DITOO":          replace(BASELINE, panel_resolution=16, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Ditoo (16×16 cube, has FM + SD + mic).",)),
    "DitooPlus":      replace(BASELINE, panel_resolution=16, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Ditoo+ variant.",)),
    "DitooMic":       replace(BASELINE, panel_resolution=16, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Ditoo Mic variant.",)),
    "DitooPro":       replace(BASELINE, panel_resolution=16, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Ditoo Pro variant.",)),
    "CyberBag":       replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Cyber Bag 16.",)),
    "Dipow35":        replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Dipow 35 (16×16, clock).",)),

    # 32×32 devices (most of the modern lineup)
    "Tivoo":          replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Tivoo (32×32 retro TV).",)),
    "TimeboxEvo":     replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Timebox Evo (32×32 cube).",)),
    "TivooMax":       replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Tivoo Max (32×32 retro TV, large).",)),
    "TIMOO":          replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Timoo (32×32 clock).",)),
    "Planet9":        replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Planet 9 (32×32 round).",)),
    "PIXOO_MAX":      replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Pixoo Max (32×32).",)),
    "PIXOO_VJ":       replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixoo VJ effects panel (32×32).",)),
    "TivooLit":       replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Tivoo Lit (32×32 with light).",)),
    "TivoomMax32":    replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Tivoo Max 32 variant.",)),
    "TivooLcd":       replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Tivoo LCD variant.",)),
    "Karaoke":        replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Divoom Karaoke (32×32).",)),
    "Lcd5Wifi":       replace(BASELINE, panel_resolution=32, has_fm=True, has_sd=True, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=True, notes=("Divoom 5\" LCD WiFi.",)),

    # 64×64 + 128×128 (large panels)
    "Pixoo64Wifi":    replace(BASELINE, panel_resolution=64, has_fm=False, has_sd=False, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixoo 64 WiFi (large panel).",)),
    "Pixoo64Wifi_2":  replace(BASELINE, panel_resolution=64, has_fm=False, has_sd=False, has_scoreboard=True, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixoo 64 WiFi v2.",)),

    # Battery / bag devices
    "Pixel_Factory":  replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixel Factory production-line device.",)),
    "PixelBag":       replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixel Bag (battery, no FM/SD).",)),
    "PixelBagM":      replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixel Bag M.",)),
    "PixelBagS":      replace(BASELINE, panel_resolution=16, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixel Bag S (16×16).",)),
    "PixelBagNew":    replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixel Bag New.",)),
    "PixelBagBIPI":   replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Pixel Bag BIPI.",)),
    "Zooe":           replace(BASELINE, panel_resolution=32, has_fm=False, has_sd=False, has_scoreboard=False, has_orientation=True, has_screen_mirror=True, has_factory_reset=True, has_mic=False, notes=("Zooe (battery, no FM/SD).",)),
}


# ── Identifier 1: explicit device_type ─────────────────────────────────────

def capabilities_for(device_type: str | None) -> Capabilities:
    """Look up capabilities by explicit device_type, or return the baseline
    if the type is unknown / unset.

    Use this when the caller knows the model. For hardware-derived
    identification of an unknown device, use ``DeviceRegistry`` or
    ``capabilities_from_manufacturer_data`` instead.
    """
    if device_type and device_type in DEVICE_CAPABILITIES:
        return DEVICE_CAPABILITIES[device_type]
    return BASELINE


# ── Identifier 2: per-install MAC registry ─────────────────────────────────
# Saved once, used forever. The user pairs each device with its model on
# first connect; the lib remembers it. This is the recommended path for
# any installation that has more than one device or that wants the
# correct capabilities without per-call kwarqs.

REGISTRY_PATH = Path(
    os.environ.get("DIVOOM_CONTROL_REGISTRY")
    or (Path.home() / ".config" / "divoom-control" / "devices.json")
)


class DeviceRegistry:
    """Per-install MAC → device_type registry. Hardware-derived
    (MAC is unique to the BLE chip).

    Usage::

        registry = DeviceRegistry()                     # default path
        registry.register("11-75-58-3f-fd-aa", "Pixoo")
        caps = registry.lookup("11-75-58-3f-fd-aa")
        assert caps.panel_resolution == 16

    Saved as JSON at ``~/.config/divoom-control/devices.json`` by
    default (overridable via ``DIVOOM_CONTROL_REGISTRY`` env var or
    the ``path`` argument). Case-insensitive MAC lookup.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else REGISTRY_PATH
        self._entries: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                self._entries = {
                    k.lower(): v for k, v in data.items() if isinstance(v, str)
                }
        except (OSError, json.JSONDecodeError) as e:
            # Corrupt file: log and start fresh. Never crash on a registry read.
            import logging
            logging.getLogger(__name__).warning(
                "DeviceRegistry: %s is corrupt (%s); starting empty.", self.path, e
            )
            self._entries = {}

    def lookup(self, mac: str) -> Optional[Capabilities]:
        """Return the registered Capabilities for this MAC, or None."""
        self._ensure_loaded()
        device_type = self._entries.get(mac.lower())
        if not device_type:
            return None
        return capabilities_for(device_type)

    def register(self, mac: str, device_type: str) -> None:
        """Add or update the MAC → device_type mapping and persist."""
        if device_type not in DEVICE_CAPABILITIES:
            raise ValueError(
                f"unknown device_type {device_type!r}; "
                f"valid: {sorted(DEVICE_CAPABILITIES.keys())}"
            )
        self._ensure_loaded()
        self._entries[mac.lower()] = device_type
        self._save()

    def unregister(self, mac: str) -> bool:
        """Remove the mapping. Returns True if it existed."""
        self._ensure_loaded()
        existed = self.path.exists() and self._entries.pop(mac.lower(), None) is not None
        if existed:
            self._save()
        return existed

    def all_entries(self) -> dict[str, str]:
        """Return a copy of the current registry (lowercased MACs)."""
        self._ensure_loaded()
        return dict(self._entries)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write with original-case MACs for human readability.
        original_case = json.loads(json.dumps(self._entries))  # shallow copy
        self.path.write_text(
            json.dumps(dict(sorted(self._entries.items())), indent=2) + "\n"
        )


# ── Identifier 3: BLE advertisement fingerprint ────────────────────────────
# bleak's ``BleakScanner.discover(..., return_adv=True)`` returns
# ``AdvertisementData`` objects with a ``manufacturer_data`` dict
# (key = Bluetooth SIG Company Identifier, value = bytes). The bytes
# are broadcast by the device hardware — no GATT connection needed.
#
# Divoom's manufacturer company ID is a Bluetooth SIG assigned number
# (commonly 0x0D00 for Shenzhen Divoom Technology Co. — verify in
# production). The exact byte layout is device-specific; this table
# is intentionally tiny. Populate it as the user identifies new
# devices via ``divoom-control identify``.

# The keys are (company_id, first_byte_of_payload_prefix) tuples.
# Value is the device_type key. The tuple is matched with manufacturer
# data starting with that prefix byte.
ADVERTISED_FINGERPRINTS: dict[tuple[int, tuple[int, ...]], str] = {
    # (0x0D00, (0x01,)):  "Pixoo",          # Pixoo 1st gen — verify byte
    # (0x0D00, (0x02,)):  "TivooMax",       # Tivoo Max — verify byte
    # Populate as the user identifies new devices.
}


def capabilities_from_manufacturer_data(
    manufacturer_data: dict[int, bytes] | None,
) -> Optional[Capabilities]:
    """Look up capabilities from a bleak ``AdvertisementData.manufacturer_data``
    dict. Returns None if no fingerprint matches.

    The fingerprint table is intentionally small — it grows as the user
    identifies new devices. If a real Divoom device is found whose
    fingerprint is not in the table, ``identify`` (a separate CLI) can
    print the raw bytes for the user to add.
    """
    if not manufacturer_data:
        return None
    for (company_id, prefix), device_type in ADVERTISED_FINGERPRINTS.items():
        payload = manufacturer_data.get(company_id)
        if not payload:
            continue
        if tuple(payload[:len(prefix)]) == prefix:
            return capabilities_for(device_type)
    return None

