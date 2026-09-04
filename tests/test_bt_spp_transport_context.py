"""Async context-manager coverage for BTSppTransport (split from
test_bt_spp_transport_coverage.py)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from divoom_lib.bt_spp_transport import BTSppTransport


def _t(**kw):
    return BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2, logger=logging.getLogger("spp_cov"), **kw)


# ── async context manager ────────────────────────────────────────────────────


class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_aenter_calls_connect_and_returns_self(self, monkeypatch):
        t = _t()
        connect_mock = AsyncMock()
        monkeypatch.setattr(t, "connect", connect_mock)
        result = await t.__aenter__()
        connect_mock.assert_called_once()
        assert result is t

    @pytest.mark.asyncio
    async def test_aexit_calls_disconnect(self, monkeypatch):
        t = _t()
        disconnect_mock = AsyncMock()
        monkeypatch.setattr(t, "disconnect", disconnect_mock)
        await t.__aexit__(None, None, None)
        disconnect_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_async_with_block(self, monkeypatch):
        t = _t()
        monkeypatch.setattr(t, "connect", AsyncMock())
        monkeypatch.setattr(t, "disconnect", AsyncMock())
        async with t as ctx:
            assert ctx is t
        t.disconnect.assert_called_once()
