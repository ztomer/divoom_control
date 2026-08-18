"""
R15 §5 — MCP tool catalog.

12 initial tools covering the main ``divoom_lib`` features. Each
tool is a small async function that takes a ``Divoom`` instance
(closed over by ``build_tool_catalog``) plus the user-supplied
arguments, and returns a JSON-serializable result.

Tool list (initial):

  - set_volume              (0-15)
  - set_brightness          (0-100)
  - set_light_mode          (named -> channel int 0-15)
  - set_weather             (temperature_c, weather enum)
  - set_alarm               (index, hour, minute, weekday_mask, ...)
  - set_radio               (freq_x10 875-1080)
  - set_low_power           (bool)
  - set_screen_orientation  (degrees, mirror)
  - show_image              (file path)
  - push_animation          (file path or base64 data, exclusive-mode)
  - play_sound              (duration_ms)
  - get_capabilities        ()
  - get_device_state        ()

Domain validation lives in the tool handler (not in JSON Schema)
because the schema only constrains the *shape* of the input — a
value of 99 for ``level`` passes the schema but is a domain error.
"""
from __future__ import annotations

import dataclasses  # used by get_capabilities' real-Divoom fallback (was NameError)
from typing import Any, Optional

from divoom_lib.models import WeatherType
from divoom_lib.mcp_server import Tool


# ── Light-mode channel names (UI-friendly -> protocol int) ────────────

LIGHT_MODE_NAMES: dict[str, int] = {
    "clock": 0,
    "lightning": 1,
    "cloud": 2,
    "vj": 3,
    "visualizer": 4,
    "design": 5,
    "scoreboard": 6,
    "animation": 7,
}


# ── Weather name -> WeatherType ──────────────────────────────────────

WEATHER_NAME_TO_TYPE: dict[str, int] = {
    "clear": WeatherType.Clear,
    "cloudy": WeatherType.CloudySky,
    "thunderstorm": WeatherType.Thunderstorm,
    "rain": WeatherType.Rain,
    "snow": WeatherType.Snow,
    "fog": WeatherType.Fog,
}


def _validate_level(name: str, value: Any, lo: int, hi: int) -> int:
    """Range-check an integer argument. Raises ``ValueError`` on failure
    so the MCP server can wrap it in a tool-level error response."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in [{lo}..{hi}] (got {value!r})")
    return value


# ── Tool handlers (each closes over the divoom instance) ─────────────


def _make_handlers(divoom) -> dict[str, Any]:
    """Build the dict of name -> async handler, parameterized over the
    connected Divoom instance."""

    async def set_volume(level: int) -> dict:
        level = _validate_level("level", level, 0, 15)
        ok = await divoom.music.set_volume(level)
        return {"ok": bool(ok), "level": level}

    async def set_brightness(level: int) -> dict:
        level = _validate_level("level", level, 0, 100)
        ok = await divoom.device.set_brightness(level)
        return {"ok": bool(ok), "level": level}

    async def set_light_mode(mode: str) -> dict:
        if not isinstance(mode, str) or mode not in LIGHT_MODE_NAMES:
            raise ValueError(
                f"mode must be one of {sorted(LIGHT_MODE_NAMES)} (got {mode!r})"
            )
        channel = LIGHT_MODE_NAMES[mode]
        ok = await divoom.control.set_light_mode(channel)
        return {"ok": bool(ok), "mode": mode, "channel": channel}

    async def set_weather(temperature_c: int, weather: str) -> dict:
        # Range matches the Weather class: -127..128.
        temperature_c = _validate_level("temperature_c", temperature_c, -127, 128)
        if not isinstance(weather, str) or weather not in WEATHER_NAME_TO_TYPE:
            raise ValueError(
                f"weather must be one of {sorted(WEATHER_NAME_TO_TYPE)} (got {weather!r})"
            )
        wt = WEATHER_NAME_TO_TYPE[weather]
        ok = await divoom.weather.set(temperature_c, wt)
        return {"ok": bool(ok), "temperature_c": temperature_c, "weather": weather}

    async def set_alarm(
        index: int,
        hour: int,
        minute: int,
        weekday_mask: int = 0,
        enabled: bool = True,
    ) -> dict:
        index = _validate_level("index", index, 0, 9)
        hour = _validate_level("hour", hour, 0, 23)
        minute = _validate_level("minute", minute, 0, 59)
        weekday_mask = _validate_level("weekday_mask", weekday_mask, 0, 127)
        # set_alarm signature: (index, status, hour, minute, week, mode, trigger_mode, fm_freq, volume)
        # mode 0 = music; trigger_mode 1 = ALARM_TRIGGER_MUSIC; no FM; default volume.
        status = 1 if enabled else 0
        ok = await divoom.alarm.set_alarm(index, status, hour, minute, weekday_mask, 0, 1)
        return {
            "ok": bool(ok),
            "index": index,
            "hour": hour,
            "minute": minute,
            "weekday_mask": weekday_mask,
            "enabled": bool(enabled),
        }

    async def set_radio(freq_x10: int) -> dict:
        freq_x10 = _validate_level("freq_x10", freq_x10, 875, 1080)
        ok = await divoom.radio.set_radio_frequency(freq_x10)
        return {"ok": bool(ok), "freq_x10": freq_x10}

    async def set_low_power(enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        ok = await divoom.device.set_low_power_switch(1 if enabled else 0)
        return {"ok": bool(ok), "enabled": bool(enabled)}

    async def set_screen_orientation(degrees: int, mirror: bool = False) -> dict:
        degrees = _validate_level("degrees", degrees, 0, 270)
        if degrees not in (0, 90, 180, 270):
            raise ValueError("degrees must be one of 0, 90, 180, 270")
        if not isinstance(mirror, bool):
            raise ValueError("mirror must be a boolean")
        # Map 0/90/180/270 to protocol ints (per design.py):
        # 0 = normal, 1 = 90, 2 = 180, 3 = 270.
        direction = {0: 0, 90: 1, 180: 2, 270: 3}[degrees]
        ok_dir = await divoom.design.set_screen_dir(direction)
        ok_mirror = await divoom.design.set_screen_mirror(bool(mirror))
        return {
            "ok": bool(ok_dir) and bool(ok_mirror),
            "degrees": degrees,
            "mirror": bool(mirror),
        }

    async def show_image(file: str) -> dict:
        """Push a local image file to the device.

        Note: takes a *local path*, not a URL. The Divoom protocol
        doesn't fetch remote URLs — clients must download first."""
        if not isinstance(file, str) or not file:
            raise ValueError("file must be a non-empty local path string")
        ok = await divoom.display.show_image(file)
        return {"ok": bool(ok), "file": file}

    async def push_animation(file: str | None = None,
                             data: str | None = None) -> dict:
        """Push a GIF/animation to the device via 0x8B 3-phase streaming.

        Provide *either* a local ``file`` path *or* base64-encoded
        ``data`` (for MCP clients without a shared filesystem).  The
        push runs inside an exclusive-mode session so the multi-phase
        0x8B sequence is never interleaved with other commands."""
        if bool(file) == bool(data):
            raise ValueError("provide exactly one of 'file' or 'data'")
        if data:
            import base64
            file_or_data = base64.b64decode(data)
        else:
            file_or_data = file  # type: ignore[assignment]
        # If divoom is a DaemonDeviceProxy, use push_animation (exclusive).
        # Otherwise fall back to display.show_image.
        from divoom_client.daemon_client import DaemonDeviceProxy
        if isinstance(divoom, DaemonDeviceProxy):
            ok = await divoom.push_animation(file_or_data)
        else:
            ok = await divoom.display.show_image(file_or_data)
        return {"ok": bool(ok)}

    async def play_sound(duration_ms: int) -> dict:
        """Beep the device for ``duration_ms`` milliseconds.

        The Divoom protocol doesn't have a "play arbitrary sound"
        command — we use the 0x23 (set keyboard) command with a
        non-standard tone as the closest equivalent. Many devices
        no-op this; the tool is best-effort."""
        duration_ms = _validate_level("duration_ms", duration_ms, 100, 3000)
        # The closest we have: send a "hot" command (0x26, 0x01) which
        # triggers a tone on most Divoom firmware. We don't have a
        # direct duration arg, so we report best-effort.
        try:
            ok = await divoom.control.set_hot(1)
        except AttributeError:
            ok = False
        return {"ok": bool(ok), "duration_ms": duration_ms}

    async def get_capabilities() -> dict:
        """Read-only: return the device's capabilities (panel resolution,
        speaker, clock, etc.)."""
        import inspect

        caps = divoom.capabilities
        # When ``divoom`` is a DaemonDeviceProxy (R28), ``caps`` is itself a
        # proxy and ``caps.to_dict()`` returns an awaitable that routes through
        # the daemon's device_call; for a real Divoom it's a sync dataclass
        # method. Handle both.
        to_dict = getattr(caps, "to_dict", None)
        if callable(to_dict):
            res = to_dict()
            if inspect.isawaitable(res):
                res = await res
            return res
        if dataclasses.is_dataclass(caps):
            return {f.name: getattr(caps, f.name) for f in dataclasses.fields(caps)}
        return {"raw": str(caps)}

    async def get_device_state() -> dict:
        """Read-only: snapshot the device's current volume, brightness,
        light mode, screen orientation, and mirror state.

        All values are best-effort; if a getter raises (e.g. the
        device is mid-command), that key is reported as ``None`` so
        callers can tell the read failed without crashing."""
        import dataclasses

        async def _safe(coro, default=None):
            try:
                return await coro
            except Exception:
                return default

        volume = await _safe(divoom.music.get_volume())
        brightness = await _safe(divoom.device.get_brightness())
        light_mode = await _safe(divoom.control.get_light_mode())
        screen_dir = await _safe(divoom.design.get_screen_dir())
        screen_mirror = await _safe(divoom.design.get_screen_mirror())
        return {
            "volume": volume,
            "brightness": brightness,
            "light_mode": light_mode,
            "screen_orientation": screen_dir,
            "mirror": screen_mirror,
        }

    return {
        "set_volume": set_volume,
        "set_brightness": set_brightness,
        "set_light_mode": set_light_mode,
        "set_weather": set_weather,
        "set_alarm": set_alarm,
        "set_radio": set_radio,
        "set_low_power": set_low_power,
        "set_screen_orientation": set_screen_orientation,
        "show_image": show_image,
        "push_animation": push_animation,
        "play_sound": play_sound,
        "get_capabilities": get_capabilities,
        "get_device_state": get_device_state,
    }


# ── Schemas (one per tool) ────────────────────────────────────────────


_SCHEMAS: dict[str, dict] = {
    "set_volume": {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "minimum": 0, "maximum": 15},
        },
        "required": ["level"],
    },
    "set_brightness": {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["level"],
    },
    "set_light_mode": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": sorted(LIGHT_MODE_NAMES),
            },
        },
        "required": ["mode"],
    },
    "set_weather": {
        "type": "object",
        "properties": {
            "temperature_c": {"type": "integer", "minimum": -127, "maximum": 128},
            "weather": {
                "type": "string",
                "enum": sorted(WEATHER_NAME_TO_TYPE),
            },
        },
        "required": ["temperature_c", "weather"],
    },
    "set_alarm": {
        "type": "object",
        "properties": {
            "index": {"type": "integer", "minimum": 0, "maximum": 9},
            "hour": {"type": "integer", "minimum": 0, "maximum": 23},
            "minute": {"type": "integer", "minimum": 0, "maximum": 59},
            "weekday_mask": {
                "type": "integer",
                "minimum": 0,
                "maximum": 127,
                "description": "Bitmask: bit 0 = Sunday .. bit 6 = Saturday.",
            },
            "enabled": {"type": "boolean"},
        },
        "required": ["index", "hour", "minute"],
    },
    "set_radio": {
        "type": "object",
        "properties": {
            "freq_x10": {
                "type": "integer",
                "minimum": 875,
                "maximum": 1080,
                "description": "Frequency in MHz × 10 (e.g. 875 = 87.5 MHz).",
            },
        },
        "required": ["freq_x10"],
    },
    "set_low_power": {
        "type": "object",
        "properties": {"enabled": {"type": "boolean"}},
        "required": ["enabled"],
    },
    "set_screen_orientation": {
        "type": "object",
        "properties": {
            "degrees": {
                "type": "integer",
                "enum": [0, 90, 180, 270],
            },
            "mirror": {"type": "boolean"},
        },
        "required": ["degrees"],
    },
    "show_image": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Local filesystem path to the image to push.",
            },
        },
        "required": ["file"],
    },
    "push_animation": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Local filesystem path to the GIF/animation to push.",
            },
            "data": {
                "type": "string",
                "description": "Base64-encoded GIF/animation bytes (alternative to 'file').",
            },
        },
        "oneOf": [
            {"required": ["file"]},
            {"required": ["data"]},
        ],
    },
    "play_sound": {
        "type": "object",
        "properties": {
            "duration_ms": {"type": "integer", "minimum": 100, "maximum": 3000},
        },
        "required": ["duration_ms"],
    },
    "get_capabilities": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "get_device_state": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


_DESCRIPTIONS: dict[str, str] = {
    "set_volume": "Set the device's speaker volume (0-15).",
    "set_brightness": "Set the device's display brightness (0-100).",
    "set_light_mode": "Switch the active channel (clock, lightning, cloud, vj, visualizer, design, scoreboard, animation).",
    "set_weather": "Push a temperature + weather icon to the device's built-in weather widget.",
    "set_alarm": "Set or disable one of the device's 10 alarms.",
    "set_radio": "Tune the FM radio (freq_x10 = MHz × 10, e.g. 875 = 87.5).",
    "set_low_power": "Enable or disable the device's low-power mode.",
    "set_screen_orientation": "Rotate the device's display 0/90/180/270 degrees; optionally mirror/flip.",
    "show_image": "Push a local image file to the device (palette-quantized + bit-packed on the wire).",
    "push_animation": "Push a GIF/animation via 0x8B 3-phase streaming inside an exclusive session. Provide 'file' (path) or 'data' (base64).",
    "play_sound": "Beep the device for 100-3000 ms (best-effort; some firmware no-ops).",
    "get_capabilities": "Read the device's static capabilities (panel resolution, has_speaker, etc.).",
    "get_device_state": "Read the device's current volume, brightness, channel, orientation, and mirror state.",
}


def build_tool_catalog(divoom) -> list[Tool]:
    """Build the full tool catalog parameterized over a connected Divoom."""
    import dataclasses  # noqa: F401  (used in get_capabilities via dataclass check)
    handlers = _make_handlers(divoom)
    catalog: list[Tool] = []
    for name, schema in _SCHEMAS.items():
        catalog.append(
            Tool(
                name=name,
                description=_DESCRIPTIONS[name],
                input_schema=schema,
                handler=handlers[name],
            )
        )
    return catalog
