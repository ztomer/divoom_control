"""Regression: a Divoom cloud outage (e.g. guest login RC=10 "Command is not
match") must not crash or hammer the app.

- get_cached_credentials() never touches the network and never raises.
- get_credentials() fails fast inside a cooldown after a network failure, so a
  polled/transport-status path can't re-trigger a failing login every call.
"""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import divoom_auth


@pytest.fixture(autouse=True)
def _reset_cooldown(monkeypatch):
    monkeypatch.setattr(divoom_auth, "_last_auth_fail_at", 0.0, raising=False)
    # No email/password configured -> guest path; no cached token.
    monkeypatch.setattr(divoom_auth, "_load_config", lambda: ("", ""))
    monkeypatch.setattr(divoom_auth, "_load_cache", lambda: None)
    monkeypatch.setattr(divoom_auth, "_save_cache", lambda creds: None)


def test_get_cached_credentials_never_networks_or_raises(monkeypatch):
    calls = {"guest": 0}

    def boom():
        calls["guest"] += 1
        raise RuntimeError("UserNewGuest failed: RC=10 msg=Command is not match")

    monkeypatch.setattr(divoom_auth, "_login_guest", boom)
    # Even with the cloud down, the cache-only accessor is silent + safe.
    assert divoom_auth.get_cached_credentials() is None
    assert calls["guest"] == 0  # never hit the network


def test_get_credentials_cooldown_after_failure(monkeypatch):
    calls = {"guest": 0}

    def boom():
        calls["guest"] += 1
        raise RuntimeError("UserNewGuest failed: RC=10 msg=Command is not match")

    monkeypatch.setattr(divoom_auth, "_login_guest", boom)

    # First call actually attempts the login and propagates the failure.
    with pytest.raises(RuntimeError):
        divoom_auth.get_credentials()
    assert calls["guest"] == 1

    # Subsequent calls within the cooldown fail fast WITHOUT another network hit.
    for _ in range(5):
        with pytest.raises(RuntimeError):
            divoom_auth.get_credentials()
    assert calls["guest"] == 1  # no re-hammering the cloud


def test_valid_cache_short_circuits_even_in_cooldown(monkeypatch):
    monkeypatch.setattr(divoom_auth, "_last_auth_fail_at", 9e18, raising=False)  # "always cooling down"
    good = divoom_auth.DivoomCredentials(token=123, user_id=456)
    monkeypatch.setattr(divoom_auth, "_load_cache", lambda: good)
    # A valid cached token is returned regardless of the cooldown.
    assert divoom_auth.get_credentials() is good


def test_force_refresh_with_account_relogins_even_in_cooldown(monkeypatch):
    """R45 #2: a genuine token expiry (force_refresh) on a CONFIGURED account
    re-submits the stored email/password even inside the failure cooldown — the
    cooldown only gates the guest fallback / polled callers."""
    monkeypatch.setattr(divoom_auth, "_last_auth_fail_at", 9e18, raising=False)  # in cooldown
    monkeypatch.setattr(divoom_auth, "_load_config", lambda: ("user@example.com", "pw"))
    good = divoom_auth.DivoomCredentials(token=1, user_id=2)
    calls = {"email": 0, "guest": 0}

    def _email(email, pw):
        calls["email"] += 1
        return good

    def _guest():
        calls["guest"] += 1
        raise RuntimeError("should not reach guest")

    monkeypatch.setattr(divoom_auth, "_login_email", _email)
    monkeypatch.setattr(divoom_auth, "_login_guest", _guest)

    out = divoom_auth.get_credentials(force_refresh=True)
    assert out is good
    assert calls["email"] == 1 and calls["guest"] == 0


def test_cooldown_still_gates_account_without_force_refresh(monkeypatch):
    """Without force_refresh, a polled caller in cooldown must NOT re-hit the
    network even with an account configured (no hammering)."""
    monkeypatch.setattr(divoom_auth, "_last_auth_fail_at", 9e18, raising=False)  # in cooldown
    monkeypatch.setattr(divoom_auth, "_load_config", lambda: ("user@example.com", "pw"))
    calls = {"email": 0}
    monkeypatch.setattr(divoom_auth, "_login_email",
                        lambda e, p: calls.__setitem__("email", calls["email"] + 1))
    with pytest.raises(RuntimeError):
        divoom_auth.get_credentials()           # force_refresh defaults False
    assert calls["email"] == 0                   # cooldown gated it
