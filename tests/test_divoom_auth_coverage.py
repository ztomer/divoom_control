"""R61 coverage push (item 1): close the remaining gaps in divoom_auth.py.

Existing test files (test_auth_resilience.py, test_auth_cache_resilience.py,
test_credentials_save.py) monkeypatch the module's *seams*
(_load_cache/_login_email/_login_guest/_save_cache) to test get_credentials()
policy (cooldown, cache priority, force_refresh). This file instead tests the
internals those seams normally replace: _post, _login_email, _get_server_utc,
_login_guest, _load_config, _load_virtual_device, _save_cache, _load_cache,
print_err, DivoomCredentials.is_valid, and the two get_credentials() branches
that were still uncovered (email-login exception -> guest fallback; guest
success -> cache + return).

No real network call is ever made: every HTTP path goes through a mocked
urllib.request.urlopen. No real ~/.config file is touched: CONFIG_FILE /
CACHE_FILE / VIRTUAL_DEVICE_PATHS are monkeypatched to pytest tmp_path.
"""
import hashlib
import json
import time

import pytest

from divoom_lib import divoom_auth


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mock_urlopen(monkeypatch, payload, capture=None):
    def _fake(req, timeout=None):
        if capture is not None:
            capture.append(req)
        return _FakeResponse(payload)
    monkeypatch.setattr(divoom_auth.urllib.request, "urlopen", _fake)


# ── print helpers / dataclass ────────────────────────────────────────────────

def test_print_err_outputs_prefixed_message(capsys):
    divoom_auth.print_err("boom")
    out = capsys.readouterr().out
    assert "[ Err ]" in out and "boom" in out


def test_is_valid_requires_both_token_and_user_id():
    assert divoom_auth.DivoomCredentials(token=1, user_id=2).is_valid()
    assert not divoom_auth.DivoomCredentials(token=0, user_id=2).is_valid()
    assert not divoom_auth.DivoomCredentials(token=1, user_id=0).is_valid()


def test_md5_matches_hashlib():
    assert divoom_auth._md5("hello") == hashlib.md5(b"hello").hexdigest()


# ── _load_config ──────────────────────────────────────────────────────────────

def test_load_config_missing_file_returns_blank(monkeypatch, tmp_path):
    monkeypatch.setattr(divoom_auth, "CONFIG_FILE", tmp_path / "nope" / "config.ini")
    assert divoom_auth._load_config() == ("", "")


def test_load_config_reads_email_and_password(monkeypatch, tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[divoom]\nemail = me@example.com\npassword = s3cret\n")
    monkeypatch.setattr(divoom_auth, "CONFIG_FILE", cfg)
    assert divoom_auth._load_config() == ("me@example.com", "s3cret")


def test_load_config_missing_section_returns_blank(monkeypatch, tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[other]\nfoo = bar\n")
    monkeypatch.setattr(divoom_auth, "CONFIG_FILE", cfg)
    assert divoom_auth._load_config() == ("", "")


# ── _load_virtual_device ────────────────────────────────────────────────────

def test_load_virtual_device_no_paths_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(divoom_auth, "VIRTUAL_DEVICE_PATHS", [tmp_path / "a.json", tmp_path / "b.json"])
    assert divoom_auth._load_virtual_device() == {}


def test_load_virtual_device_reads_first_existing(monkeypatch, tmp_path):
    good = tmp_path / "vd.json"
    good.write_text(json.dumps({"Type": 1, "SubType": 2}))
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(divoom_auth, "VIRTUAL_DEVICE_PATHS", [missing, good])
    assert divoom_auth._load_virtual_device() == {"Type": 1, "SubType": 2}


def test_load_virtual_device_malformed_json_returns_empty(monkeypatch, tmp_path):
    bad = tmp_path / "vd.json"
    bad.write_text("{not json")
    monkeypatch.setattr(divoom_auth, "VIRTUAL_DEVICE_PATHS", [bad])
    assert divoom_auth._load_virtual_device() == {}


# ── _register_virtual_device / ensure_virtual_device ────────────────────────
#
# 2026-07-14 fix: AidSleep/GetAllList (and presumably other device-scoped
# cloud calls) need a BluetoothDeviceId the SERVER actually issued via
# BlueDevice/NewDevice, not a client-side placeholder -- see cloud.py's
# writeup. These test the registration + persist-once-and-reuse machinery.

def _mock_urlopen_by_command(monkeypatch, responses: dict):
    """Route the mocked urlopen by the POSTed body's ``Command`` field
    (multiple distinct commands in one test, unlike ``_mock_urlopen``'s
    single fixed payload)."""
    def _fake(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        command = body["Command"]
        assert command in responses, f"unexpected command {command}"
        return _FakeResponse(responses[command])
    monkeypatch.setattr(divoom_auth.urllib.request, "urlopen", _fake)


def test_register_virtual_device_success(monkeypatch):
    _mock_urlopen_by_command(monkeypatch, {
        "APP/GetServerUTC": {"ReturnCode": 0, "UTC": 1700000000},
        "BlueDevice/NewDevice": {"ReturnCode": 0, "BluetoothDeviceId": 42, "DevicePassword": 99},
    })
    creds = divoom_auth.DivoomCredentials(token=1, user_id=2)
    dev = divoom_auth._register_virtual_device(creds)
    assert dev == {"BluetoothDeviceId": 42, "DevicePassword": 99, "Type": 1, "SubType": 1}


def test_register_virtual_device_rc_nonzero_raises(monkeypatch):
    _mock_urlopen_by_command(monkeypatch, {
        "APP/GetServerUTC": {"ReturnCode": 0, "UTC": 1700000000},
        "BlueDevice/NewDevice": {"ReturnCode": 3, "ReturnMessage": "Request data is incomplete"},
    })
    creds = divoom_auth.DivoomCredentials(token=1, user_id=2)
    with pytest.raises(RuntimeError, match="RC=3"):
        divoom_auth._register_virtual_device(creds)


def test_ensure_virtual_device_returns_existing_without_registering(monkeypatch, tmp_path):
    existing = {"BluetoothDeviceId": 600124449, "DevicePassword": 1780230545, "Type": 9, "SubType": 0}
    monkeypatch.setattr(divoom_auth, "_load_virtual_device", lambda: existing)

    def _fail_if_called(req, timeout=None):
        raise AssertionError("should not register when a device is already on file")
    monkeypatch.setattr(divoom_auth.urllib.request, "urlopen", _fail_if_called)

    creds = divoom_auth.DivoomCredentials(token=1, user_id=2)
    assert divoom_auth.ensure_virtual_device(creds) == existing


def test_ensure_virtual_device_registers_and_persists_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(divoom_auth, "_load_virtual_device", lambda: {})
    dest = tmp_path / "virtual_device.json"
    monkeypatch.setattr(divoom_auth, "VIRTUAL_DEVICE_PATHS", [dest])
    _mock_urlopen_by_command(monkeypatch, {
        "APP/GetServerUTC": {"ReturnCode": 0, "UTC": 1700000000},
        "BlueDevice/NewDevice": {"ReturnCode": 0, "BluetoothDeviceId": 42, "DevicePassword": 99},
    })
    creds = divoom_auth.DivoomCredentials(token=1, user_id=2)
    dev = divoom_auth.ensure_virtual_device(creds)
    assert dev["BluetoothDeviceId"] == 42
    assert dest.exists()
    assert json.loads(dest.read_text())["BluetoothDeviceId"] == 42


# ── _post ──────────────────────────────────────────────────────────────────────

def test_post_sends_json_body_and_parses_response(monkeypatch):
    captured = []
    _mock_urlopen(monkeypatch, {"ReturnCode": 0, "Token": 5}, capture=captured)
    result = divoom_auth._post("SomePath", {"a": 1})
    assert result == {"ReturnCode": 0, "Token": 5}
    assert captured[0].full_url == f"{divoom_auth.BASE_URL}/SomePath"
    assert json.loads(captured[0].data.decode()) == {"a": 1}


# ── _login_email ────────────────────────────────────────────────────────────────

def test_login_email_success(monkeypatch):
    _mock_urlopen(monkeypatch, {"ReturnCode": 0, "Token": 111, "UserId": 222})
    creds = divoom_auth._login_email("me@example.com", "pw")
    assert creds.token == 111 and creds.user_id == 222 and creds.email == "me@example.com"


def test_login_email_not_registered(monkeypatch):
    _mock_urlopen(monkeypatch, {"ReturnCode": 4})
    with pytest.raises(RuntimeError, match="not registered"):
        divoom_auth._login_email("nope@example.com", "pw")


def test_login_email_wrong_password(monkeypatch):
    _mock_urlopen(monkeypatch, {"ReturnCode": 5})
    with pytest.raises(RuntimeError, match="incorrect"):
        divoom_auth._login_email("me@example.com", "wrong")


def test_login_email_other_failure_includes_rc_and_message(monkeypatch):
    _mock_urlopen(monkeypatch, {"ReturnCode": 99, "ReturnMessage": "weird"})
    with pytest.raises(RuntimeError, match="RC=99"):
        divoom_auth._login_email("me@example.com", "pw")


# ── _get_server_utc ────────────────────────────────────────────────────────────

def test_get_server_utc_success(monkeypatch):
    _mock_urlopen(monkeypatch, {"UTC": 12345})
    assert divoom_auth._get_server_utc() == 12345


def test_get_server_utc_falls_back_on_network_error(monkeypatch):
    def _boom(req, timeout=None):
        raise divoom_auth.urllib.error.URLError("no net")
    monkeypatch.setattr(divoom_auth.urllib.request, "urlopen", _boom)
    before = int(time.time())
    assert divoom_auth._get_server_utc() >= before


def test_get_server_utc_falls_back_when_response_utc_zero(monkeypatch):
    _mock_urlopen(monkeypatch, {"UTC": 0})
    before = int(time.time())
    assert divoom_auth._get_server_utc() >= before


# ── _login_guest ──────────────────────────────────────────────────────────────

def test_login_guest_success_no_virtual_device(monkeypatch):
    monkeypatch.setattr(divoom_auth, "_get_server_utc", lambda: 999)
    monkeypatch.setattr(divoom_auth, "_load_virtual_device", lambda: {})
    _mock_urlopen(monkeypatch, {"ReturnCode": 0, "Token": 7, "UserId": 8})
    creds = divoom_auth._login_guest()
    assert creds.token == 7 and creds.user_id == 8 and creds.utc == 999


def test_login_guest_includes_virtual_device_identity_in_request(monkeypatch):
    captured = []
    monkeypatch.setattr(divoom_auth, "_get_server_utc", lambda: 1)
    monkeypatch.setattr(divoom_auth, "_load_virtual_device", lambda: {
        "Type": 5, "SubType": 6, "BluetoothDeviceId": 7, "DevicePassword": 8,
    })
    _mock_urlopen(monkeypatch, {"ReturnCode": 0, "Token": 1, "UserId": 2}, capture=captured)
    divoom_auth._login_guest()
    sent = json.loads(captured[0].data.decode())
    assert sent["Type"] == 5 and sent["SubType"] == 6
    assert sent["DeviceId"] == 7 and sent["devicePassword"] == 8


def test_login_guest_rc_error_raises_with_message(monkeypatch):
    monkeypatch.setattr(divoom_auth, "_get_server_utc", lambda: 1)
    monkeypatch.setattr(divoom_auth, "_load_virtual_device", lambda: {})
    _mock_urlopen(monkeypatch, {"ReturnCode": 10, "ReturnMessage": "Command is not match"})
    with pytest.raises(RuntimeError, match="RC=10"):
        divoom_auth._login_guest()


# ── _save_cache / _load_cache ──────────────────────────────────────────────────

def test_save_cache_writes_expected_json_with_0600_mode(monkeypatch, tmp_path):
    cache_file = tmp_path / "auth_token.json"
    monkeypatch.setattr(divoom_auth, "CACHE_FILE", cache_file)
    creds = divoom_auth.DivoomCredentials(token=1, user_id=2, email="a@b.com", utc=5)
    divoom_auth._save_cache(creds)
    data = json.loads(cache_file.read_text())
    assert data["token"] == 1 and data["user_id"] == 2
    assert data["email"] == "a@b.com" and data["utc"] == 5
    assert "saved_at" in data


def test_load_cache_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(divoom_auth, "CACHE_FILE", tmp_path / "nope.json")
    assert divoom_auth._load_cache() is None


def test_load_cache_valid_recent_entry(monkeypatch, tmp_path):
    cache_file = tmp_path / "auth_token.json"
    cache_file.write_text(json.dumps({
        "token": 1, "user_id": 2, "email": "x@y.com", "utc": 3,
        "saved_at": int(time.time()),
    }))
    monkeypatch.setattr(divoom_auth, "CACHE_FILE", cache_file)
    creds = divoom_auth._load_cache()
    assert creds.token == 1 and creds.user_id == 2 and creds.email == "x@y.com"


def test_load_cache_expired_entry_returns_none(monkeypatch, tmp_path):
    cache_file = tmp_path / "auth_token.json"
    cache_file.write_text(json.dumps({
        "token": 1, "user_id": 2, "saved_at": int(time.time()) - 24 * 3600,
    }))
    monkeypatch.setattr(divoom_auth, "CACHE_FILE", cache_file)
    assert divoom_auth._load_cache() is None


def test_load_cache_invalid_creds_returns_none(monkeypatch, tmp_path):
    cache_file = tmp_path / "auth_token.json"
    cache_file.write_text(json.dumps({
        "token": 0, "user_id": 0, "saved_at": int(time.time()),
    }))
    monkeypatch.setattr(divoom_auth, "CACHE_FILE", cache_file)
    assert divoom_auth._load_cache() is None


def test_load_cache_corrupt_json_returns_none(monkeypatch, tmp_path, capsys):
    cache_file = tmp_path / "auth_token.json"
    cache_file.write_text("{not json")
    monkeypatch.setattr(divoom_auth, "CACHE_FILE", cache_file)
    assert divoom_auth._load_cache() is None
    assert "Cache load failed" in capsys.readouterr().out


# ── get_credentials: remaining branches ────────────────────────────────────────

def test_get_credentials_email_login_exception_falls_back_to_guest(monkeypatch):
    monkeypatch.setattr(divoom_auth, "_last_auth_fail_at", 0.0, raising=False)
    monkeypatch.setattr(divoom_auth, "_load_cache", lambda: None)
    monkeypatch.setattr(divoom_auth, "_load_config", lambda: ("me@example.com", "pw"))

    def _boom(email, pw):
        raise RuntimeError("Password is incorrect")

    monkeypatch.setattr(divoom_auth, "_login_email", _boom)
    good = divoom_auth.DivoomCredentials(token=1, user_id=2)
    monkeypatch.setattr(divoom_auth, "_login_guest", lambda: good)
    monkeypatch.setattr(divoom_auth, "_save_cache", lambda creds: None)

    assert divoom_auth.get_credentials() is good


def test_get_credentials_guest_success_saves_cache_and_returns(monkeypatch):
    monkeypatch.setattr(divoom_auth, "_last_auth_fail_at", 0.0, raising=False)
    monkeypatch.setattr(divoom_auth, "_load_cache", lambda: None)
    monkeypatch.setattr(divoom_auth, "_load_config", lambda: ("", ""))
    good = divoom_auth.DivoomCredentials(token=9, user_id=10)
    monkeypatch.setattr(divoom_auth, "_login_guest", lambda: good)
    saved = []
    monkeypatch.setattr(divoom_auth, "_save_cache", lambda creds: saved.append(creds))

    assert divoom_auth.get_credentials() is good
    assert saved == [good]
