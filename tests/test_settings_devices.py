"""The settings' `[gallery]` table — the ONE home for the hot channel's devices.

The loop used to keep its own list in ``hotchannel.json`` and it was EMPTY:
the push was enabled, scheduled, and reached nobody. The app's settings
already knew the devices, so the fact moved there and nowhere else.

These tests pin the rules the daemon's Rust side also implements
(``divoomd/src/settings_devices.rs``), and the two are held in step by
``tools/check_hotchannel_parity.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import settings_devices as sd


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "config.ini"
    monkeypatch.setenv(sd.CONFIG_ENV, str(path))
    return path


SETTINGS = """\
[gui]
timeout = 120

[gallery]
f90d2cc9-420e-65f9-9e06-f9554470fced = 18
e9a41e1e-9a96-974f-ce44-54f16d616f28 = 18
2b471aee-a9bd-24ab-7d5f-4afd88c16eeb = 18
a9fccb71-3d3d-4de3-c381-0de382cdc4aa = 17
gallery_sort = 1
gallery_file_size = 1
"""


def test_the_settings_name_the_devices_and_their_gallery(settings_file):
    settings_file.write_text(SETTINGS, encoding="utf-8")
    assert sd.registered_devices() == [
        ("f90d2cc9-420e-65f9-9e06-f9554470fced", 18),
        ("e9a41e1e-9a96-974f-ce44-54f16d616f28", 18),
        ("2b471aee-a9bd-24ab-7d5f-4afd88c16eeb", 18),
        ("a9fccb71-3d3d-4de3-c381-0de382cdc4aa", 17),
    ]


def test_the_tables_own_settings_are_not_devices(settings_file):
    """`gallery_sort` and `gallery_file_size` live in the same table. If they
    were read as devices, the loop would try to CONNECT to them."""
    settings_file.write_text(SETTINGS, encoding="utf-8")
    addresses = [addr for addr, _ in sd.registered_devices()]
    assert not any("gallery_" in addr for addr in addresses)
    assert "gallery_sort" not in addresses


def test_a_missing_file_registers_nothing(settings_file):
    assert sd.registered_devices() == []


def test_a_device_without_a_gallery_gets_the_clouds_default(settings_file):
    settings_file.write_text("[gallery]\ndefault = 17\n", encoding="utf-8")
    assert sd.device_classify("anything") == 17


def test_an_unusable_gallery_value_falls_back(settings_file):
    settings_file.write_text(
        "[gallery]\na9fccb71-3d3d-4de3-c381-0de382cdc4aa = oops\n", encoding="utf-8"
    )
    assert sd.device_classify("a9fccb71-3d3d-4de3-c381-0de382cdc4aa") == 18


def test_registering_writes_the_table_and_keeps_the_rest(settings_file):
    settings_file.write_text(SETTINGS, encoding="utf-8")
    assert sd.set_registered(["f90d2cc9-420e-65f9-9e06-f9554470fced"]) is True
    text = settings_file.read_text(encoding="utf-8")
    assert "a9fccb71-3d3d-4de3-c381-0de382cdc4aa" not in text, (
        "a device that was turned off must leave the table"
    )
    assert "gallery_sort = 1" in text, "the table's own settings must survive"
    assert "timeout = 120" in text, "the rest of the settings file must survive"
    assert sd.registered_devices() == [("f90d2cc9-420e-65f9-9e06-f9554470fced", 18)]


def test_registering_keeps_the_gallery_a_device_already_had(settings_file):
    settings_file.write_text(SETTINGS, encoding="utf-8")
    sd.set_registered(["a9fccb71-3d3d-4de3-c381-0de382cdc4aa"])
    assert sd.registered_devices() == [("a9fccb71-3d3d-4de3-c381-0de382cdc4aa", 17)]


def test_registering_can_set_the_gallery(settings_file):
    settings_file.write_text(SETTINGS, encoding="utf-8")
    sd.set_registered(
        ["a9fccb71-3d3d-4de3-c381-0de382cdc4aa"], {"a9fccb71-3d3d-4de3-c381-0de382cdc4aa": 9}
    )
    assert sd.registered_devices() == [("a9fccb71-3d3d-4de3-c381-0de382cdc4aa", 9)]


def test_a_name_that_is_not_an_address_is_not_a_device():
    assert sd.is_device_address("a9fccb71-3d3d-4de3-c381-0de382cdc4aa")
    assert sd.is_device_address("AA:BB:CC:DD:EE:FF")
    assert sd.is_device_address("LAN:192.168.1.50")
    assert not sd.is_device_address("Timoo-light-4")
    assert not sd.is_device_address("gallery_sort")
    assert not sd.is_device_address("")


def test_the_address_rule_is_the_same_case_for_case():
    """The same cases the daemon's Rust side pins
    (``divoomd/src/settings_devices.rs``): two readers of one table, so the
    table's cases live in both."""
    cases = [
        ("f90d2cc9-420e-65f9-9e06-f9554470fced", True),
        ("AA:BB:CC:DD:EE:FF", True),
        ("AA:00:00:00:00:01", True),
        ("LAN:192.168.1.50", True),
        ("gallery_sort", False),
        ("gallery_file_size", False),
        ("default", False),
        ("Timoo-light-4", False),
        ("", False),
        ("AA BB", False),
    ]
    for key, expected in cases:
        assert sd.is_device_address(key) is expected, f"address rule: {key}"
