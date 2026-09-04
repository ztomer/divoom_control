"""
transport.py — Transport layer taxonomy for divoom-control.

Every command sent to a Divoom device travels over exactly one of four
distinct transports. This module defines the authoritative enum, a
decorator for tagging methods, and the canonical routing map.

Transport Summary
-----------------
  BLE      Bluetooth Low Energy — 100 % local, no internet ever.
  LAN      Device HTTP API (:9000) — 100 % local, WiFi-enabled devices.
  CLOUD    appin.divoom-gz.com — Divoom's servers, requires account.
  EXT      3rd-party APIs (weather, stocks, fonts) — no login needed.
"""

from enum import Enum
from functools import wraps


# ── Enum ──────────────────────────────────────────────────────────────────────

class Transport(Enum):
    """The four network paths a command can take."""

    BLE   = "ble"      #  Bluetooth Low Energy — 100 % local
    LAN   = "lan"      #  LAN HTTP :9000       — 100 % local (WiFi devices)
    CLOUD = "cloud"    #  appin.divoom-gz.com  — Divoom's servers
    EXT   = "external" #  3rd-party internet   — weather / stocks / fonts

    # ── Display helpers ───────────────────────────────────────────────────────

    @property
    def badge(self) -> str:
        """Emoji badge for this transport."""
        return _BADGES[self]

    @property
    def label(self) -> str:
        """Short human-readable label."""
        return _LABELS[self]

    @property
    def description(self) -> str:
        """One-line privacy description shown in the UI legend."""
        return _DESCRIPTIONS[self]

    @property
    def is_local(self) -> bool:
        """True iff no packet ever leaves the local network."""
        return self in (Transport.BLE, Transport.LAN)

    @property
    def color_hex(self) -> str:
        """CSS hex colour for the transport badge."""
        return _COLORS[self]


_BADGES: dict[Transport, str] = {
    Transport.BLE:   "",
    Transport.LAN:   "",
    Transport.CLOUD: "",
    Transport.EXT:   "",
}

_LABELS: dict[Transport, str] = {
    Transport.BLE:   "BLE",
    Transport.LAN:   "LAN",
    Transport.CLOUD: "Divoom Cloud",
    Transport.EXT:   "External",
}

_DESCRIPTIONS: dict[Transport, str] = {
    Transport.BLE:   "Bluetooth Low Energy — 100 % local, never leaves your device.",
    Transport.LAN:   "Local Wi-Fi HTTP (:9000) — 100 % local, talks directly to the device.",
    Transport.CLOUD: "Divoom cloud (appin.divoom-gz.com) — requires internet & Divoom account.",
    Transport.EXT:   "3rd-party internet APIs (weather, stocks) — no login required.",
}

_COLORS: dict[Transport, str] = {
    Transport.BLE:   "#3b82f6",   # blue-500
    Transport.LAN:   "#22c55e",   # green-500
    Transport.CLOUD: "#f59e0b",   # amber-500
    Transport.EXT:   "#ef4444",   # red-500
}


# ── Decorator ─────────────────────────────────────────────────────────────────

def via(transport: Transport):
    """
    Tag a coroutine or function with its transport layer.

    The transport is stored as ``fn.transport`` and is readable at runtime,
    enabling introspection by the GUI and CLI without calling the method.

    Usage::

        from divoom_lib.transport import Transport, via

        class Device:
            @via(Transport.BLE)
            async def set_brightness(self, brightness: int) -> bool:
                ...
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await fn(*args, **kwargs)

        wrapper.transport = transport
        # Preserve sync functions (non-coroutines) as-is
        if not hasattr(fn, "__wrapped__"):
            import inspect
            if not inspect.iscoroutinefunction(fn):
                @wraps(fn)
                def sync_wrapper(*args, **kwargs):
                    return fn(*args, **kwargs)
                sync_wrapper.transport = transport
                return sync_wrapper

        return wrapper
    return decorator


# ── Command routing map ───────────────────────────────────────────────────────

COMMAND_TRANSPORT_MAP: dict[str, Transport] = {
    # ──  BLE — always local, Bluetooth only ────────────────────────────────
    "brightness":       Transport.BLE,
    "channel":          Transport.BLE,
    "clock_display":    Transport.BLE,
    "animation":        Transport.BLE,
    "text_scroll":      Transport.BLE,
    "timer":            Transport.BLE,
    "scoreboard":       Transport.BLE,
    "alarm":            Transport.BLE,
    "fm_radio":         Transport.BLE,
    "volume":           Transport.BLE,
    "notifications":    Transport.BLE,
    "screen_rotation":  Transport.BLE,
    "boot_animation":   Transport.BLE,
    "factory_reset":    Transport.BLE,
    "device_name":      Transport.BLE,
    "sleep":            Transport.BLE,
    "drawing":          Transport.BLE,
    "sand_paint":       Transport.BLE,
    "font_transfer":    Transport.BLE,
    "temp_unit":        Transport.BLE,
    "work_mode":        Transport.BLE,
    "auto_power_off":   Transport.BLE,
    "sound_control":    Transport.BLE,
    "net_temp":         Transport.BLE,   # push weather data over BLE

    # ──  LAN — local WiFi HTTP :9000 (WiFi-capable devices only) ───────────
    "lan_brightness":   Transport.LAN,
    "lan_channel":      Transport.LAN,
    "lan_clock":        Transport.LAN,
    "lan_timer":        Transport.LAN,
    "lan_scoreboard":   Transport.LAN,
    "lan_noise":        Transport.LAN,
    "lan_screen":       Transport.LAN,
    "lan_ambient":      Transport.LAN,
    "lan_rgb":          Transport.LAN,
    "lan_photo_album":  Transport.LAN,
    "lan_eq":           Transport.LAN,

    # ──  Divoom Cloud — appin.divoom-gz.com (requires account) ─────────────
    "gallery_browse":   Transport.CLOUD,
    "clock_face_store": Transport.CLOUD,
    "user_auth":        Transport.CLOUD,
    "upload_artwork":   Transport.CLOUD,
    "community":        Transport.CLOUD,
    "cloud_alarm":      Transport.CLOUD,
    "pomodoro":         Transport.CLOUD,
    "white_noise":      Transport.CLOUD,
    "tts_voice":        Transport.CLOUD,

    # ──  External — 3rd-party APIs, no account required ────────────────────
    "weather":          Transport.EXT,
    "stock_ticker":     Transport.EXT,
    "music_metadata":   Transport.EXT,
    "album_art":        Transport.EXT,
}


def transport_for(feature: str) -> Transport | None:
    """Look up the transport for a named feature group."""
    return COMMAND_TRANSPORT_MAP.get(feature)
