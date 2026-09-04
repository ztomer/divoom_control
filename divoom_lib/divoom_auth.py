#!/usr/bin/env python3
"""
divoom_auth.py — Divoom cloud API authentication module.

Supports two authentication paths:
  1. Email/password login (UserLogin) — preferred, uses config.ini credentials
  2. Guest login (User/NewGuest) — fallback, no account needed

HMAC-MD5 UTC signing discovered via APK static analysis (P2/a.java):
  key = b"DivoomBluetoothDevice<>?"
  utc_encrypt = hmac_md5(key, str(utc))
"""

import configparser
import hashlib
import hmac
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path


def print_info(message):
    print(f"[ ==> ] {message}")

def print_wrn(message):
    print(f"[ Wrn ] {message}")

def print_err(message):
    print(f"[ Err ] {message}")

def print_ok(message):
    print(f"[ Ok  ] {message}")

def _redact(secret) -> str:
    """Mask a bearer token for logs: keep a short prefix for correlation, never
    the full value. The daemon is commonly launched with stdout → logfile, so
    printing the live cloud token in clear let anyone with log access replay it."""
    s = str(secret or "")
    if len(s) <= 4:
        return "****"
    return f"{s[:4]}…({len(s)} chars)"


BASE_URL   = "https://appin.divoom-gz.com"
HMAC_KEY   = b"DivoomBluetoothDevice<>?"  # from P2/a.java
TIMEOUT    = 15
CONFIG_FILE = Path.home() / ".config" / "divoom-control" / "config.ini"
CACHE_FILE  = Path.home() / ".config" / "divoom-control" / "auth_token.json"
VIRTUAL_DEVICE_PATHS = [
    Path.home() / ".config" / "divoom-control" / "virtual_device.json",
    Path(__file__).resolve().parent.parent / "api_scraper" / "divoom_docs" / "virtual_device.json",
]


def _load_virtual_device() -> dict:
    """Return the bound device's identity (BluetoothDeviceId / DevicePassword /
    Type / SubType) used to sign cloud requests. Mirrors the lookup in
    ``divoom_gui.gui_api``. Empty dict if no virtual device is configured."""
    for p in VIRTUAL_DEVICE_PATHS:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return {}


@dataclass
class DivoomCredentials:
    token:   int
    user_id: int
    email:   str = ""
    utc:     int = 0

    def is_valid(self) -> bool:
        return self.token != 0 and self.user_id != 0


def _load_config() -> tuple[str, str]:
    """Read email + password from config.ini."""
    cfg = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        return "", ""
    cfg.read(CONFIG_FILE)
    email    = cfg.get("divoom", "email",    fallback="")
    password = cfg.get("divoom", "password", fallback="")
    return email, password


def _hmac_md5(message: str) -> str:
    """Compute HMAC-MD5 as lowercase hex. From P2/a.java."""
    h = hmac.new(HMAC_KEY, message.encode("utf-8"), hashlib.md5)
    return h.hexdigest()


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _post(path: str, body: dict) -> dict:
    url     = f"{BASE_URL}/{path}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Connection":   "close",
            "User-Agent":   "okhttp/4.12.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Virtual device registration (BlueDevice/NewDevice) ─────────────────────────
#
# 2026-07-14: this is the fix for the AidSleep/GetAllList RC=3 mystery (see
# divoom_lib/cloud.py's writeup). Every device-scoped cloud call (AidSleep's
# browse endpoints, and presumably others) requires a BluetoothDeviceId that
# the SERVER has actually seen via BlueDevice/NewDevice — a client-supplied
# placeholder (0, or any made-up int) doesn't satisfy it, confirmed by
# Device/GetListV2 showing zero bound devices for an account that had never
# called this. `bluetooth/f.java`'s `f(type, subType)` ("applyNewBlueDevice")
# is the real app's registration call: APP/GetServerUTC for a signed
# timestamp, then BlueDevice/NewDevice with UTC + UTCEncrypt (same HMAC-MD5
# scheme as guest login) + Type/SubType, returning a real BluetoothDeviceId +
# DevicePassword. Confirmed live 2026-07-14 — registering with Type=1/
# SubType=1 (an arbitrary but accepted device-class pair; the exact real
# caller values weren't decompiled, but the server accepted 0/0 and 1/1
# identically) immediately unblocked AidSleep/GetAllList (RC=3 -> RC=0, real
# sleep-sound catalog returned).

def _register_virtual_device(creds: "DivoomCredentials") -> dict:
    """Register a new virtual Bluetooth device identity with the cloud
    (``BlueDevice/NewDevice``), returning ``{"BluetoothDeviceId", "DevicePassword",
    "Type", "SubType"}``. Raises RuntimeError on failure. Does NOT persist —
    see :func:`ensure_virtual_device`."""
    utc = _get_server_utc()
    utc_str = str(utc)
    utc_encrypt = _hmac_md5(utc_str)
    type_, subtype = 1, 1
    body = {
        "Command":  "BlueDevice/NewDevice",
        "Token":    creds.token,
        "UserId":   creds.user_id,
        "DeviceId": 0,
        "UTC":      utc_str,
        "UTCEncrypt": utc_encrypt,
        "Type":     type_,
        "SubType":  subtype,
    }
    data = _post("BlueDevice/NewDevice", body)
    rc = data.get("ReturnCode", -1)
    if rc != 0:
        raise RuntimeError(f"BlueDevice/NewDevice failed: RC={rc} msg={data.get('ReturnMessage')}")
    return {
        "BluetoothDeviceId": data.get("BluetoothDeviceId", 0),
        "DevicePassword":    data.get("DevicePassword", 0),
        "Type":              type_,
        "SubType":           subtype,
    }


def ensure_virtual_device(creds: "DivoomCredentials") -> dict:
    """Like :func:`_load_virtual_device`, but registers a new server-side
    device identity via :func:`_register_virtual_device` and persists it if
    none exists yet (or the cached one lacks a real ``BluetoothDeviceId``).
    One-time cost per machine/account — the result is cached to
    ``VIRTUAL_DEVICE_PATHS[0]`` and reused on every later call."""
    dev = _load_virtual_device()
    if dev.get("BluetoothDeviceId"):
        return dev
    print_info("No bound device on file — registering a new one via BlueDevice/NewDevice ...")
    dev = _register_virtual_device(creds)
    print_ok(f"Registered virtual device: BluetoothDeviceId={dev['BluetoothDeviceId']}")
    from divoom_lib.utils.atomic_io import atomic_write_text
    path = VIRTUAL_DEVICE_PATHS[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(dev, indent=2), mode=0o600)
    return dev


# ── Auth path 1: Email / Password ─────────────────────────────────────────────

def _login_email(email: str, password: str) -> DivoomCredentials:
    """
    POST /UserLogin with MD5-hashed password.
    From LoginServer.java z() method + UserLoginRequest.java.
    """
    print_info(f"Logging in as {email!r} ...")
    body = {
        "Email":         email,
        "Password":      _md5(password),
        "TimeZone":      "+0",
        "CountryISOCode": "US",
        "Language":      "en",
        "Token":         0,
        "UserId":        0,
        "DeviceId":      0,
    }
    data = _post("UserLogin", body)
    rc   = data.get("ReturnCode", -1)

    if rc == 4:
        raise RuntimeError(f"Email not registered: {email!r}")
    if rc == 5:
        raise RuntimeError("Password is incorrect")
    if rc != 0:
        raise RuntimeError(f"UserLogin failed: RC={rc} msg={data.get('ReturnMessage')}")

    token   = data.get("Token",  0)
    user_id = data.get("UserId", 0)
    print_ok(f"Logged in: UserId={user_id} Token={_redact(token)}")
    return DivoomCredentials(token=token, user_id=user_id, email=email)


# ── Auth path 2: Guest (HMAC-UTC) ─────────────────────────────────────────────

def _get_server_utc() -> int:
    try:
        data = _post("APP/GetServerUTC", {"Command": "APP/GetServerUTC"})
        utc  = data.get("UTC", 0)
        if utc:
            print_ok(f"Server UTC: {utc}")
            return utc
    except Exception as e:
        print_wrn(f"APP/GetServerUTC failed ({e}), using local time")
    return int(time.time())


def _login_guest() -> DivoomCredentials:
    """
    HMAC-UTC guest login. From LoginServer.java q() + P2/a.java.
    """
    print_info("Attempting guest authentication ...")
    utc         = _get_server_utc()
    utc_str     = str(utc)
    utc_encrypt = _hmac_md5(utc_str)
    print_info(f"UTC={utc_str}  UTCEncrypt={utc_encrypt}")

    # R61 fix: the server (post-auth-flow-change) requires the bound device's
    # identity on User/NewGuest — a request without Type/SubType/DeviceId/
    # devicePassword is rejected with RC=10. The fields come from the virtual
    # device file (same source the GUI loads). Matches decompiled
    # BlueDeviceNewDeviceRequest (type/subType/utc/utcEncrypt) + BaseRequestJson
    # (DeviceId/devicePassword).
    dev = _load_virtual_device()
    body = {
        "Command":       "User/NewGuest",
        "UTC":           utc_str,
        "UTCEncrypt":    utc_encrypt,
        "Type":          dev.get("Type", 0),
        "SubType":       dev.get("SubType", 0),
        "DeviceId":      dev.get("BluetoothDeviceId", 0),
        "devicePassword": dev.get("DevicePassword", 0),
        "Token":         0,
        "UserId":        0,
    }
    data = _post("User/NewGuest", body)
    rc   = data.get("ReturnCode", -1)

    if rc != 0:
        raise RuntimeError(f"UserNewGuest failed: RC={rc} msg={data.get('ReturnMessage')}")

    token   = data.get("Token",  0)
    user_id = data.get("UserId", 0)
    print_ok(f"Guest credentials: UserId={user_id} Token={_redact(token)}")
    return DivoomCredentials(token=token, user_id=user_id, utc=utc)


# ── Cache ─────────────────────────────────────────────────────────────────────

def _save_cache(creds: DivoomCredentials) -> None:
    from divoom_lib.utils.atomic_io import atomic_write_text
    # A1 atomic + A4 0600: the token cache is a secret — never world-readable,
    # never half-written.
    atomic_write_text(CACHE_FILE, json.dumps({
        "token":    creds.token,
        "user_id":  creds.user_id,
        "email":    creds.email,
        "utc":      creds.utc,
        "saved_at": int(time.time()),
    }, indent=2), mode=0o600)
    print_info(f"Credentials cached to {CACHE_FILE}")


def _load_cache() -> DivoomCredentials | None:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        age  = int(time.time()) - data.get("saved_at", 0)
        # Email login tokens seem long-lived; cache for 23 hours
        if age > 23 * 3600:
            print_info("Cached token expired (>23h), re-authenticating")
            return None
        creds = DivoomCredentials(
            token=data["token"], user_id=data["user_id"],
            email=data.get("email", ""), utc=data.get("utc", 0),
        )
        if creds.is_valid():
            print_ok(f"Using cached credentials: UserId={creds.user_id} (email={creds.email or 'guest'})")
            return creds
    except Exception as e:
        print_wrn(f"Cache load failed: {e}")
    return None


# ── Public API ────────────────────────────────────────────────────────────────

# Negative cache: after a network auth attempt fails, don't hammer the Divoom
# cloud on every subsequent call (the GUI polls cloud-backed features). Within
# the cooldown, get_credentials() fails fast without touching the network.
_AUTH_FAIL_COOLDOWN = 120  # seconds
_last_auth_fail_at: float = 0.0


def get_cached_credentials() -> DivoomCredentials | None:
    """Return valid cached credentials if present, else None. **Never** performs
    a network login and **never** raises — safe for hot/polled paths such as the
    transport-status panel, which must not initiate (or block on) a cloud login.
    """
    try:
        return _load_cache()
    except Exception as e:  # pragma: no cover - cache read is already defensive
        print_wrn(f"Cached credential read failed: {e}")
        return None


def get_credentials(force_refresh: bool = False) -> DivoomCredentials:
    """
    Obtain valid Divoom credentials.
    Priority: cached → email/password login → guest fallback.

    Raises RuntimeError if no cached token is available and a network login
    fails (or was recently failing — see the cooldown). Callers that must not
    crash on a cloud outage should use get_cached_credentials() or wrap this.
    """
    global _last_auth_fail_at

    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached

    email, password = _load_config()
    since_fail = time.time() - _last_auth_fail_at
    in_cooldown = since_fail < _AUTH_FAIL_COOLDOWN

    # R45 #2: a configured account is ALWAYS allowed to re-submit its stored
    # email/password on a genuine token expiry (force_refresh) — the creds don't
    # change, only the token does. The cooldown below only protects the guest
    # fallback / polled callers from hammering a down/changed cloud.
    if email and password and (force_refresh or not in_cooldown):
        try:
            creds = _login_email(email, password)
        except Exception as e:
            print_wrn(f"Email login failed: {e} — falling back to guest")
        else:
            # A cache-WRITE failure (disk full / read-only ~/.config) must NOT
            # discard a SUCCESSFUL login → don't silently drop a valid account to
            # a guest token. Caching is best-effort; the creds are already valid.
            try:
                _save_cache(creds)
            except Exception as e:
                print_wrn(f"Could not cache auth token: {e}")
            return creds

    # Fail fast inside the cooldown window so a down cloud can't be hammered.
    if in_cooldown:
        raise RuntimeError(
            f"Divoom cloud auth unavailable (retry in "
            f"{int(_AUTH_FAIL_COOLDOWN - since_fail)}s)"
        )

    try:
        creds = _login_guest()
    except Exception:
        _last_auth_fail_at = time.time()
        raise
    _save_cache(creds)
    return creds


if __name__ == "__main__":
    import sys
    force = "--refresh" in sys.argv
    creds = get_credentials(force_refresh=force)
    print(f"\nToken:  {creds.token}")
    print(f"UserId: {creds.user_id}")
    print(f"Email:  {creds.email or '(guest)'}")
