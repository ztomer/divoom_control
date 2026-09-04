"""R53.42: a SUCCESSFUL email login must not be discarded just because caching
the token failed (disk full / read-only ~/.config). The old code wrapped
_login_email AND _save_cache in one try/except, so a cache-write OSError was
caught as "Email login failed — falling back to guest", silently dropping a
valid authenticated account to a guest token.

Teeth: collapse the login/cache handling back into one try and this test sees
the guest fallback instead of the real creds.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import divoom_lib.divoom_auth as auth


def test_valid_login_survives_cache_write_failure(monkeypatch):
    sentinel_creds = object()
    guest_calls = []

    monkeypatch.setattr(auth, "_load_config", lambda: ("user@example.com", "pw"))
    monkeypatch.setattr(auth, "_login_email", lambda _e, _p: sentinel_creds)

    def _cache_boom(_creds):
        raise OSError("disk full / read-only config dir")

    monkeypatch.setattr(auth, "_save_cache", _cache_boom)

    def _guest():
        guest_calls.append(1)
        return object()

    monkeypatch.setattr(auth, "_login_guest", _guest)

    result = auth.get_credentials(force_refresh=True)

    assert result is sentinel_creds, "valid login must survive a cache-write failure"
    assert guest_calls == [], "must not fall back to guest after a successful login"
