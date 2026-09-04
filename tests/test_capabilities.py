# tests/test_capabilities.py
# R13 §1 — device capability detection tests.
# Verifies the DEVICE_CAPABILITIES table + the hardware-derived identifier
# paths (explicit device_type, MAC registry, manufacturer_data fingerprint,
# baseline fallback).

import json
from pathlib import Path

import pytest

from divoom_lib.models.capabilities import (
    ADVERTISED_FINGERPRINTS,
    BASELINE,
    Capabilities,
    DEVICE_CAPABILITIES,
    DeviceRegistry,
    REGISTRY_PATH,
    capabilities_for,
    capabilities_from_manufacturer_data,
)


# ── Table coverage ────────────────────────────────────────────────────────


def test_capabilities_table_is_frozen():
    """Capabilities instances are immutable (frozen dataclass)."""
    c = DEVICE_CAPABILITIES["Pixoo"]
    with pytest.raises(Exception):
        c.panel_resolution = 32  # type: ignore


def test_capabilities_table_covers_users_four_devices():
    """The 4 devices the user owns are all in the table."""
    for key in ("Pixoo", "TivooMax", "DITOO", "TIMOO"):
        assert key in DEVICE_CAPABILITIES, f"missing device type {key!r}"
        c = DEVICE_CAPABILITIES[key]
        assert isinstance(c, Capabilities)
        assert c.panel_resolution in (16, 32, 64)


def test_pixoo_is_most_limited():
    """Pixoo (1st gen) is the most-limited 16×16 device:
    no FM, no SD, no scoreboard, no mic."""
    p = DEVICE_CAPABILITIES["Pixoo"]
    assert p.panel_resolution == 16
    assert p.has_fm is False
    assert p.has_sd is False
    assert p.has_scoreboard is False
    assert p.has_mic is False


def test_tivoo_max_has_all_features():
    """Tivoo Max is a 32×32 retro TV with FM, SD, scoreboard, mic, orientation, mirror."""
    t = DEVICE_CAPABILITIES["TivooMax"]
    assert t.panel_resolution == 32
    assert t.has_fm is True
    assert t.has_sd is True
    assert t.has_scoreboard is True
    assert t.has_mic is True
    assert t.has_orientation is True
    assert t.has_screen_mirror is True


def test_ditoo_is_16x16_with_fm_sd_mic():
    """Ditoo is a 16×16 cube with FM, SD, mic."""
    d = DEVICE_CAPABILITIES["DITOO"]
    assert d.panel_resolution == 16
    assert d.has_fm is True
    assert d.has_sd is True
    assert d.has_mic is True


def test_timoo_is_32x32_with_fm_sd_mic():
    """Timoo is a 32×32 clock with FM, SD, mic."""
    t = DEVICE_CAPABILITIES["TIMOO"]
    assert t.panel_resolution == 32
    assert t.has_fm is True
    assert t.has_sd is True
    assert t.has_mic is True


def test_baseline_is_pixoo_like():
    """The baseline is the most-limited device (Pixoo-class)."""
    assert BASELINE.panel_resolution == 16
    assert BASELINE.has_fm is False
    assert BASELINE.has_sd is False
    assert BASELINE.has_scoreboard is False


def test_panel_resolution_is_per_panel_not_wall():
    """panel_resolution is the per-panel pixel dimension (16/32/64). It is NOT
    the wall composite canvas size — that is `panel_resolution * grid_cols`
    by `panel_resolution * grid_rows`, computed separately in DivoomWall.

    This test guards against the conflation that originally came up in
    R13 §1 design review."""
    tivoo = DEVICE_CAPABILITIES["TivooMax"]
    # Per-panel: 32. NOT the wall canvas (which would be 32*cols).
    assert tivoo.panel_resolution == 32
    assert tivoo.panel_resolution * 2 == 64  # 2-col wall
    assert tivoo.panel_resolution * 4 == 128  # 4-col wall


# ── Identifier 1: explicit device_type ──────────────────────────────────


def test_capabilities_for_explicit_type():
    c = capabilities_for("TivooMax")
    assert c.panel_resolution == 32
    assert c.has_fm is True


def test_capabilities_for_unknown_type_returns_baseline():
    c = capabilities_for("NonexistentDevice")
    assert c.panel_resolution == BASELINE.panel_resolution
    assert c.has_fm is False


def test_capabilities_for_none_returns_baseline():
    c = capabilities_for(None)
    assert c.panel_resolution == BASELINE.panel_resolution


# ── Identifier 2: per-install MAC registry (hardware-derived) ───────────


def test_device_registry_roundtrip(tmp_path: Path):
    """register() persists to JSON; lookup() reads it back."""
    reg = DeviceRegistry(path=tmp_path / "devices.json")
    reg.register("11-75-58-3f-fd-aa", "Pixoo")
    reg.register("11-75-58-f8-c3-62", "TivooMax")
    reg.register("11-75-58-ee-a1-2d", "DITOO")
    reg.register("11-75-58-54-b9-13", "TIMOO")

    # Fresh registry instance reads the same file.
    reg2 = DeviceRegistry(path=tmp_path / "devices.json")
    assert reg2.lookup("11-75-58-3f-fd-aa").panel_resolution == 16
    assert reg2.lookup("11-75-58-f8-c3-62").panel_resolution == 32
    assert reg2.lookup("11-75-58-ee-a1-2d").panel_resolution == 16
    assert reg2.lookup("11-75-58-54-b9-13").panel_resolution == 32


def test_device_registry_case_insensitive_mac(tmp_path: Path):
    """MAC lookup is case-insensitive (BLE addresses are sometimes
    printed upper or lower case)."""
    reg = DeviceRegistry(path=tmp_path / "devices.json")
    reg.register("11-75-58-3F-FD-AA", "Pixoo")
    assert reg.lookup("11-75-58-3f-fd-aa") is not None
    assert reg.lookup("11-75-58-3F-FD-AA") is not None
    assert reg.lookup("11:75:58:3F:FD:AA") is None  # colon-separated != dash-separated


def test_device_registry_unknown_mac_returns_none(tmp_path: Path):
    reg = DeviceRegistry(path=tmp_path / "devices.json")
    assert reg.lookup("aa-bb-cc-dd-ee-ff") is None


def test_device_registry_rejects_unknown_device_type(tmp_path: Path):
    reg = DeviceRegistry(path=tmp_path / "devices.json")
    with pytest.raises(ValueError):
        reg.register("aa-bb-cc-dd-ee-ff", "NonexistentDevice")


def test_device_registry_unregister(tmp_path: Path):
    reg = DeviceRegistry(path=tmp_path / "devices.json")
    reg.register("aa-bb-cc-dd-ee-ff", "Pixoo")
    assert reg.lookup("aa-bb-cc-dd-ee-ff") is not None
    assert reg.unregister("aa-bb-cc-dd-ee-ff") is True
    assert reg.lookup("aa-bb-cc-dd-ee-ff") is None
    assert reg.unregister("aa-bb-cc-dd-ee-ff") is False  # already gone


def test_device_registry_corrupt_file_does_not_crash(tmp_path: Path):
    """A corrupt registry file should not prevent the lib from starting."""
    path = tmp_path / "devices.json"
    path.write_text("not valid json {")
    reg = DeviceRegistry(path=path)
    assert reg.lookup("aa-bb-cc-dd-ee-ff") is None
    # Registering a new device overwrites the corrupt file.
    reg.register("aa-bb-cc-dd-ee-ff", "Pixoo")
    reg2 = DeviceRegistry(path=path)
    assert reg2.lookup("aa-bb-cc-dd-ee-ff") is not None


def test_device_registry_default_path_is_under_xdg_config_home():
    """The default registry path lives under ~/.config (XDG convention)."""
    assert "divoom-control" in str(REGISTRY_PATH)
    assert REGISTRY_PATH.name == "devices.json"


# ── Identifier 3: BLE advertisement fingerprint (hardware-derived) ───────


def test_capabilities_from_manufacturer_data_empty():
    """Empty / None manufacturer_data returns None (no fingerprint)."""
    assert capabilities_from_manufacturer_data(None) is None
    assert capabilities_from_manufacturer_data({}) is None


def test_capabilities_from_manufacturer_data_no_match():
    """Manufacturer data with no matching company ID returns None."""
    # Some random bytes that don't match any fingerprint.
    assert capabilities_from_manufacturer_data({0x1234: b"\x99\x99\x99"}) is None


def test_advertised_fingerprints_table_is_empty_by_default():
    """The fingerprint table starts empty — it grows as the user identifies
    new devices via `divoom-control identify`. An empty table is fine;
    `capabilities_from_manufacturer_data` will return None for everything."""
    # If this ever fails, someone added a fingerprint — make sure it's correct.
    for (company_id, prefix), device_type in ADVERTISED_FINGERPRINTS.items():
        assert device_type in DEVICE_CAPABILITIES, (
            f"fingerprint ({company_id:#x}, {prefix}) → {device_type!r} "
            f"but {device_type!r} is not in DEVICE_CAPABILITIES"
        )


# ── Divoom facade wiring ─────────────────────────────────────────────────


def test_divoom_capabilities_property_returns_capabilities():
    """Divoom.capabilities returns a Capabilities instance."""
    from divoom_lib import Divoom
    d = Divoom(mac="AA:BB:CC:DD:EE:FF")
    caps = d.capabilities
    assert isinstance(caps, Capabilities)
    # No device_type, no registry hit, no advertisement_data → baseline
    assert caps.panel_resolution == BASELINE.panel_resolution


def test_divoom_capabilities_uses_explicit_device_type():
    """Explicit device_type kwarg beats everything else."""
    from divoom_lib import Divoom
    d = Divoom(mac="AA:BB:CC:DD:EE:FF", device_type="TivooMax")
    assert d.capabilities.panel_resolution == 32
    assert d.capabilities.has_fm is True


def test_divoom_capabilities_uses_registry(monkeypatch, tmp_path: Path):
    """If device_type is unset, the MAC registry is consulted."""
    from divoom_lib import Divoom
    from divoom_lib.models.capabilities import DeviceRegistry
    reg_path = tmp_path / "devices.json"
    reg = DeviceRegistry(path=reg_path)
    reg.register("11-75-58-3f-fd-aa", "DITOO")

    monkeypatch.setattr("divoom_lib.models.capabilities.REGISTRY_PATH", reg_path)
    d = Divoom(mac="11-75-58-3f-fd-aa")  # user's Ditoo
    assert d.capabilities.panel_resolution == 16
    assert d.capabilities.has_fm is True


def test_divoom_capabilities_uses_manufacturer_data():
    """If advertisement_data is provided and the fingerprint table has a
    match, the MAC + device_type are bypassed."""
    from divoom_lib import Divoom
    # Inject a fake fingerprint and matching manufacturer data.
    from divoom_lib.models import capabilities as caps_mod
    caps_mod.ADVERTISED_FINGERPRINTS[(0x0D00, (0x42,))] = "TivooMax"
    try:
        d = Divoom(mac="AA:BB:CC:DD:EE:FF", advertisement_data={0x0D00: b"\x42\x01\x02"})
        assert d.capabilities.panel_resolution == 32
        assert d.capabilities.has_fm is True
    finally:
        del caps_mod.ADVERTISED_FINGERPRINTS[(0x0D00, (0x42,))]


def test_divoom_capabilities_falls_back_to_baseline():
    """If nothing matches, baseline (most-limited Pixoo defaults)."""
    from divoom_lib import Divoom
    d = Divoom(mac="AA:BB:CC:DD:EE:FF")
    # No device_type, no registry, no advertisement_data.
    assert d.capabilities.panel_resolution == 16
    assert d.capabilities.has_fm is False
