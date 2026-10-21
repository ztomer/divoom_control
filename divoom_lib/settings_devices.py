"""The devices the app's settings register — the ONE home for that fact.

The hot-channel loop used to keep its own list of devices in
``hotchannel.json`` (``targets``) and its own per-device gallery
(``device_galleries``). That list was EMPTY: the loop was enabled, it was
scheduled, and it fetched nothing and pushed nothing — for 36 days, with
nothing anywhere saying so. Meanwhile the app's settings already knew the
devices: ``config.ini``'s ``[gallery]`` table is keyed by device address and
holds the gallery that device wants.

So the fact lives in the settings, and only in the settings. The GUI writes it
(the Routines card's device toggles, the gallery card's per-device style) and
the daemon reads it (``divoomd/src/settings_devices.rs``). There is no second
list to fill and no second list to drift.

The table's shape::

    [gallery]
    f90d2cc9-420e-65f9-9e06-f9554470fced = 18   <- a device and the gallery it wants
    gallery_sort = 1                             <- the table's own settings
    gallery_file_size = 1

``RESERVED_KEYS`` are the table's own settings, not devices. Anything else that
is not a device address is a FINDING: the loop cannot resolve it, and it says
so rather than skipping it in silence.
"""
from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path

logger = logging.getLogger("divoom_gui")

# The gallery a device gets when the settings name none for it: the cloud's
# own "Recommend" gallery (classify 18), which is what the owner calls
# "monthly best". The same constant as the daemon's
# `cloud_category::DEFAULT_GALLERY_CLASSIFY`.
DEFAULT_CLASSIFY = 18

# The `[gallery]` table's own keys — settings, NOT devices.
RESERVED_KEYS = ("default", "gallery_sort", "gallery_file_size")

# The environment override, so a test can point the table somewhere else.
CONFIG_ENV = "DIVOOM_CONTROL_CONFIG"


def config_path() -> Path:
    """Where the settings live."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    return Path.home() / ".config" / "divoom-control" / "config.ini"


def _read_parser() -> configparser.ConfigParser:
    """The settings file, parsed. Never raises."""
    parser = configparser.ConfigParser()
    path = config_path()
    if path.exists():
        try:
            parser.read(path, encoding="utf-8")
        except Exception as e:  # a broken settings file is not a crash
            logger.warning("Could not read %s: %s", path, e)
    return parser


def is_device_address(key: str) -> bool:
    """Whether a ``[gallery]`` key names a device the daemon can connect to.

    The table is keyed by device address: the UUID-shaped id the iOS-LE
    protocol uses (what the daemon's scan reports), a MAC, or a ``LAN:``
    address. Anything else is not a device.

    The shape: hex digits and separators only, with at least one separator
    (every address this estate has carries one — dashes in the UUID form,
    colons in the MAC form) and at least four hex digits. ``gallery_sort``
    and ``gallery_file_size`` fail on the characters alone.

    The same rule, in the same words, is in the daemon's
    ``divoomd/src/settings_devices.rs``; the two are the same fact.
    """
    key = (key or "").strip()
    if not key or any(ch.isspace() for ch in key):
        return False
    if key.upper().startswith("LAN:"):
        parts = key[4:].split(".")
        return len(parts) == 4 and all(p.isdigit() for p in parts)
    hex_digits = sum(1 for ch in key if ch in "0123456789abcdefABCDEF")
    separators = sum(1 for ch in key if ch in "-:")
    return (
        hex_digits >= 4
        and separators >= 1
        and hex_digits + separators == len(key)
        and len(key) <= 38
    )


def registered_devices() -> list[tuple[str, int]]:
    """The devices the settings register, with the gallery each one wants.

    A device's gallery is its own entry, else the table's ``default``, else
    the cloud's own default.
    """
    parser = _read_parser()
    if not parser.has_section("gallery"):
        return []
    raw = dict(parser.items("gallery"))
    fallback = _as_classify(raw.get("default")) or DEFAULT_CLASSIFY
    devices: list[tuple[str, int]] = []
    for key, value in raw.items():
        if key.lower() in RESERVED_KEYS or not is_device_address(key):
            continue
        devices.append((key, _as_classify(value) or fallback))
    return devices


def device_classify(address: str) -> int:
    """The gallery one device wants."""
    for registered, classify in registered_devices():
        if registered == address:
            return classify
    parser = _read_parser()
    if parser.has_section("gallery"):
        fallback = _as_classify(dict(parser.items("gallery")).get("default"))
        if fallback:
            return fallback
    return DEFAULT_CLASSIFY


def _as_classify(value) -> int | None:
    """A gallery id, or ``None`` when the value is not one."""
    try:
        classify = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return classify if classify > 0 else None


def set_registered(addresses, galleries=None) -> bool:
    """Register exactly ``addresses`` as the devices the hot channel reaches.

    ``galleries`` optionally carries a per-device gallery (address → id); an
    address that already had one keeps it. The table's own settings
    (``gallery_sort``, ``gallery_file_size``, ``default``) are preserved, and
    the rest of the settings file is untouched.
    """
    from divoom_lib.utils.atomic_io import atomic_write_config

    path = config_path()
    parser = _read_parser()
    if not parser.has_section("gallery"):
        parser.add_section("gallery")

    existing = {addr: classify for addr, classify in registered_devices()}
    wanted = [str(a).strip() for a in (addresses or []) if str(a).strip()]
    wanted_galleries = galleries if isinstance(galleries, dict) else {}

    kept = {
        key: value
        for key, value in parser.items("gallery")
        if key.lower() in RESERVED_KEYS
    }
    parser["gallery"] = kept

    for address in wanted:
        classify = _as_classify(wanted_galleries.get(address))
        if classify is None:
            classify = existing.get(address) or DEFAULT_CLASSIFY
        parser["gallery"][address] = str(classify)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_config(path, parser, mode=0o600)  # config.ini holds creds
        return True
    except Exception as e:
        logger.error("Could not write the gallery table to %s: %s", path, e)
        return False
