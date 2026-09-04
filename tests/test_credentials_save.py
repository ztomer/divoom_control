"""Saving credentials DELEGATES to the daemon, and passes a blank through.

**These tests changed shape in R72 P1.1, and the reason matters.** They used to
assert the contents of `config.ini` after `save_credentials` -- because the GUI
wrote that file itself. It no longer does: the daemon owns the credential store,
and `save_credentials` is now one call to it.

The invariant they were written to protect has NOT moved out of the codebase,
it moved DOWN. "A blank password keeps the stored one" is now
`cloud_store::save_config`'s job and is tested in Rust, at both the helper and
the caller (`save_config_at_keeps_the_password_when_given_a_blank_one`). What
is left for Python is the half only Python can get wrong: **passing the blank
through instead of filtering it out.**

That distinction is the whole point. A GUI that helpfully skipped the call when
the password was empty, or substituted the stored one, would look correct here
and would silently stop the email-only save from ever reaching the daemon. So
the assertions below are about what is SENT, not about what is stored.

The original bug, for context: the settings form never re-populates the password
field, so a plain re-save submits `""`. Overwriting the stored password with
that erased the credential, and the next 23h token-cache expiry degraded the
account to a guest token -- "credentials get erased from time to time".
"""
from __future__ import annotations

import pytest

from divoom_gui.presets_manager import PresetsManagerMixin


class _Creds:
    def __init__(self, valid=True, email="me@example.com"):
        self._valid = valid
        self.email = email

    def is_valid(self):
        return self._valid


class _FakeClient:
    """Records what the GUI sent, and answers like the daemon."""

    def __init__(self, reply=None, boom=False):
        self.calls: list[tuple] = []
        self._reply = reply if reply is not None else _Creds()
        self._boom = boom

    def save_credentials(self, email, password):
        self.calls.append((email, password))
        if self._boom:
            raise RuntimeError("daemon said no")
        return self._reply


class _Host(PresetsManagerMixin):
    def __init__(self, client):
        self.cached_creds = None
        self._fake = client

    def _client(self):
        return self._fake


def test_a_blank_password_is_PASSED_THROUGH_not_filtered():
    """The half only the client can get wrong.

    An empty password is MEANINGFUL -- the daemon reads it as "keep the stored
    one". A GUI that skipped the call, or helpfully substituted something, would
    make the email-only save unreachable while looking perfectly sensible.
    """
    client = _FakeClient()
    host = _Host(client)
    assert host.save_credentials("me@example.com", "") is True
    assert client.calls == [("me@example.com", "")], client.calls


def test_a_real_password_is_sent_verbatim():
    client = _FakeClient()
    host = _Host(client)
    assert host.save_credentials("me@example.com", "s3cret") is True
    assert client.calls == [("me@example.com", "s3cret")], client.calls


def test_the_gui_no_longer_writes_config_ini_itself(tmp_path, monkeypatch):
    """The duplicate is gone, not merely bypassed.

    Pins the absence of the second implementation: with the daemon answering,
    nothing under a redirected HOME should be touched by this call.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    client = _FakeClient()
    _Host(client).save_credentials("me@example.com", "s3cret")
    assert not list(tmp_path.rglob("config.ini")), (
        f"save_credentials still writes config.ini: {list(tmp_path.rglob('*'))}")


def test_the_daemons_answer_decides_the_result():
    """An invalid credential is a FAILED save, even though the call succeeded."""
    host = _Host(_FakeClient(reply=_Creds(valid=False)))
    assert host.save_credentials("me@example.com", "s3cret") is False


def test_no_daemon_is_a_failure_not_a_crash():
    class _NoClient(_Host):
        def _client(self):
            return None

    assert _NoClient(_FakeClient()).save_credentials("a@b.com", "pw") is False


def test_a_daemon_error_is_reported_not_raised():
    """A raise here would surface in the pywebview bridge thread as a dead button."""
    host = _Host(_FakeClient(boom=True))
    assert host.save_credentials("a@b.com", "pw") is False


def test_the_cached_credential_is_updated_from_the_reply():
    """`load_config` reads `cached_creds`; a stale one shows the wrong account."""
    client = _FakeClient(reply=_Creds(email="new@example.com"))
    host = _Host(client)
    host.save_credentials("new@example.com", "pw")
    assert host.cached_creds is not None
    assert host.cached_creds.email == "new@example.com"
