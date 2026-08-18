"""
R14 §2 — tests for the custom notification routing JSON loader.

These tests are filesystem-only; no macOS / no BLE / no asyncio.
The loader is in ``gui/macos_notifications.py`` (the GUI module
that owns the DB-poll monitor); tests live here because the loader
is a lib-level concern, not a GUI rendering concern.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from divoom_client.macos_notifications import (
    DEFAULT_ROUTING,
    MacAppRouter,
    ROUTING_PATH,
    load_routing_table,
    save_routing_table,
)
from divoom_lib.models import NOTIFICATION_APPS


# ── load_routing_table ────────────────────────────────────────────────


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    p = tmp_path / "does-not-exist.json"
    rules = load_routing_table(p)
    assert rules == DEFAULT_ROUTING


def test_load_returns_defaults_when_configured_path_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ROUTING_PATH is resolved (from the env var) at IMPORT time, so a
    # post-import setenv has no effect — patch the bound module attribute,
    # which is what load_routing_table(None) reads at call time. (Setting the
    # env var here used to make the test depend on the absence of the user's
    # real ~/.config file, which is flaky.)
    # ROUTING_PATH + load_routing_table now live in notification_router (the
    # routing concern was split out of macos_notifications for the 500-LOC cap);
    # patch the attribute load_routing_table actually reads.
    import divoom_client.notification_router as nrouter
    monkeypatch.setattr(nrouter, "ROUTING_PATH", tmp_path / "nope.json")
    rules = load_routing_table()
    assert rules == DEFAULT_ROUTING


def test_load_reads_valid_file(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text(json.dumps([
        ["whatsapp", NOTIFICATION_APPS["WHATSAPP"]],
        ["com.apple.mail", NOTIFICATION_APPS["TEXT_MESSAGE"]],
    ]))
    rules = load_routing_table(p)
    assert ("whatsapp", NOTIFICATION_APPS["WHATSAPP"]) in rules
    assert ("com.apple.mail", NOTIFICATION_APPS["TEXT_MESSAGE"]) in rules


def test_load_drops_invalid_app_type(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text(json.dumps([
        ["valid",   NOTIFICATION_APPS["WHATSAPP"]],
        ["invalid", 999],   # not in NOTIFICATION_APPS
        ["zero",    0],     # not in NOTIFICATION_APPS
        ["neg",    -1],     # not in NOTIFICATION_APPS
    ]))
    rules = load_routing_table(p)
    substrs = [r[0] for r in rules]
    assert "valid" in substrs
    assert "invalid" not in substrs
    assert "zero" not in substrs
    assert "neg" not in substrs


def test_load_drops_malformed_entries(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text(json.dumps([
        ["ok",         1],
        ["missing"],                            # wrong arity
        [2, "ok"],                              # wrong type
        ["", 1],                                # empty substring
        ["badtype",  "not-a-number"],           # non-int app_type
    ]))
    rules = load_routing_table(p)
    substrs = [r[0] for r in rules]
    assert substrs == ["ok"]


def test_load_returns_defaults_on_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text("{ this is not valid json")
    rules = load_routing_table(p)
    assert rules == DEFAULT_ROUTING


def test_load_returns_defaults_when_root_not_a_list(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text(json.dumps({"whatsapp": 6}))  # object, not list
    rules = load_routing_table(p)
    assert rules == DEFAULT_ROUTING


def test_load_returns_defaults_when_file_has_no_valid_entries(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text(json.dumps([["only-bad", 9999]]))
    rules = load_routing_table(p)
    assert rules == DEFAULT_ROUTING


def test_load_logs_warning_on_corrupt_file(tmp_path: Path, caplog) -> None:
    import logging
    p = tmp_path / "routing.json"
    p.write_text("not json at all")
    with caplog.at_level(logging.WARNING, logger="divoom_client.macos_notifications"):
        load_routing_table(p)
    assert any("corrupt" in m.lower() for m in caplog.text.splitlines()), caplog.text


# ── save_routing_table ────────────────────────────────────────────────


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deeper" / "routing.json"
    save_routing_table([("whatsapp", 6)], p)
    assert p.exists()


def test_save_writes_sorted_json(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    save_routing_table([
        ("zeta",  1),
        ("alpha", 2),
        ("mu",    3),
    ], p)
    written = json.loads(p.read_text())
    substrs = [entry[0] for entry in written]
    assert substrs == sorted(substrs) == ["alpha", "mu", "zeta"]


def test_save_drops_invalid_entries(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    save_routing_table([
        ("good",   1),
        ("bad",    999),   # invalid app_type
        ("empty",  1),     # valid, but...
    ], p)
    written = json.loads(p.read_text())
    substrs = [entry[0] for entry in written]
    assert "good"  in substrs
    assert "empty" in substrs
    assert "bad"   not in substrs


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    rules_in = [
        ("whatsapp",     NOTIFICATION_APPS["WHATSAPP"]),
        ("com.apple.sms", NOTIFICATION_APPS["TEXT_MESSAGE"]),
        ("SLACK",        NOTIFICATION_APPS["MESSENGER"]),  # mixed case
    ]
    save_routing_table(rules_in, p)
    rules_out = load_routing_table(p)
    # load lower-cases substrings; the round-trip is on the *values*
    substrs_out = {s for s, _ in rules_out}
    assert substrs_out == {"whatsapp", "com.apple.sms", "slack"}


def test_save_atomic_via_temp_file(tmp_path: Path) -> None:
    """A crash mid-write must not leave a half-written routing.json."""
    p = tmp_path / "routing.json"
    save_routing_table([("whatsapp", 1)], p)
    # No .tmp sibling should remain after a successful save.
    assert not (tmp_path / "routing.json.tmp").exists()


# ── MacAppRouter.from_file ─────────────────────────────────────────────


def test_router_from_file_uses_custom_rules(tmp_path: Path) -> None:
    p = tmp_path / "routing.json"
    p.write_text(json.dumps([["my-app", NOTIFICATION_APPS["WHATSAPP"]]]))
    router = MacAppRouter.from_file(p)
    assert router.route("com.example.my-app.bundle") == NOTIFICATION_APPS["WHATSAPP"]
    # The default rules are NOT in this router (custom file is exclusive).
    assert router.route("com.whatsapp") is None


def test_router_from_file_missing_falls_back_to_defaults(tmp_path: Path) -> None:
    router = MacAppRouter.from_file(tmp_path / "no-such-file.json")
    # The default rules include whatsapp → 6.
    assert router.route("com.whatsapp") == NOTIFICATION_APPS["WHATSAPP"]


def test_router_rules_property_is_a_copy() -> None:
    """Mutating the returned list must not change the router's state."""
    router = MacAppRouter()
    view = router.rules
    view.clear()
    assert router.rules, "router.rules should still have entries after view.clear()"


# ── Default-path resolution ────────────────────────────────────────────


def test_default_routing_path_is_under_xdg_config_home() -> None:
    assert ROUTING_PATH.parent.name == "divoom-control"
    assert ROUTING_PATH.name == "notification_routing.json"
    # The XDG default is ~/.config/divoom-control/...
    if not os.environ.get("DIVOOM_CONTROL_ROUTING"):
        assert ROUTING_PATH.parent.parent.name == ".config"


def test_env_var_overrides_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "my-routing.json"
    custom.write_text(json.dumps([["custom", NOTIFICATION_APPS["WHATSAPP"]]]))
    monkeypatch.setenv("DIVOOM_CONTROL_ROUTING", str(custom))
    # The module-level constant is bound at import, but the
    # MacNotificationMonitor constructor reads the env var
    # indirectly via MacAppRouter.from_file(); we exercise the
    # underlying mechanism here.
    # Re-import to pick up the new env var? No — the public API
    # is to pass routing_path explicitly. The env var is only
    # honored by reloading the module; document that behavior.
    from importlib import reload
    # ROUTING_PATH is resolved from the env var at import of notification_router
    # (where it now lives), so reload THAT module to pick up the override.
    import divoom_client.notification_router as nrouter
    reload(nrouter)
    try:
        assert str(nrouter.ROUTING_PATH) == str(custom)
    finally:
        # Reset by removing the env var and reloading again.
        monkeypatch.delenv("DIVOOM_CONTROL_ROUTING", raising=False)
        reload(nrouter)
