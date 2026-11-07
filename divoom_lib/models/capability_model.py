# divoom_lib/models/capability_model.py
# The Capabilities record and the BASELINE (most-limited) row. Split out of
# capabilities.py so the per-device table (capability_table.py) can import it
# without a cycle; capabilities.py re-exports both.

from __future__ import annotations

from dataclasses import dataclass, field


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

    panel_resolution: int  # 16 / 32 / 64 (per-panel pixels, square)
    has_fm: bool  # FM radio chip
    has_sd: bool  # SD card slot for music
    has_lightning: bool  # 0x45 channel 0x01 (light effects)
    has_scoreboard: bool  # 0x45 channel 0x06 (sports scoreboard)
    has_anim_8b: bool  # 0x8B 3-phase animation streaming
    has_orientation: bool  # 0xBD 0x23 (rotate display)
    has_screen_mirror: bool  # 0xBD 0x24 (mirror display)
    has_factory_reset: bool  # 0xBD 0x25 (factory reset)
    has_alarm: bool  # 0x42 / 0x43 (alarms)
    has_sleep: bool  # 0x40 / 0x41 (sleep aid)
    has_weather: bool  # 0x5D / 0x5E (weather widget)
    has_low_power: bool  # 0xB2 / 0xB3 (low power mode)
    has_24h_clock: bool  # 0x2C (12/24h clock)
    has_temp_unit: bool  # 0x2B (°C/°F)
    has_mic: bool  # device has a microphone
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
