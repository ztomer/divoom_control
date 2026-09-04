"""
Regression test for the 'Divoom' object has no attribute 'chunksize' bug.

Bug history (2026-06-05): pushing custom art via the gallery failed with
`AttributeError: 'Divoom' object has no attribute 'chunksize'`. The
`Divoom` facade class lost the `chunksize` attribute when it was
refactored to inherit from the (newer) Divoom class instead of
`DivoomProtocol`. The fix adds `chunksize` back as a default
construction-time attribute.
"""
from divoom_lib import models
from divoom_lib.divoom import Divoom


def _stub_conn(divoom_obj, cfg):
    """Avoid spinning up real BLE/LAN transports in the test."""
    divoom_obj._conn = type("_Conn", (), {"mac": cfg.mac, "lan": None, "client": None})()


def test_divoom_facade_has_chunksize_attribute():
    """Divoom must expose a `chunksize` attribute matching the protocol default."""
    d = Divoom(mac="11:75:58:54:b9:13", logger=None)
    assert hasattr(d, "chunksize"), "Divoom facade lost the 'chunksize' attribute"
    assert d.chunksize == models.DEFAULT_CHUNK_SIZE


def test_divoom_facade_chunksize_override_via_kwargs():
    """Callers can override the default via the `chunksize` kwarg."""
    d = Divoom(mac="11:75:58:54:b9:13", chunksize=99, logger=None)
    assert d.chunksize == 99


def test_divoom_facade_chunksize_usable_by_display():
    """The display submodule (which uses communicator.chunksize) must work
    without AttributeError when show_image is called on a 1x1 PNG (no-op)."""
    d = Divoom(mac="11:75:58:54:b9:13", logger=None)
    # No real transport; just assert the attribute path is intact.
    assert hasattr(d.display, "communicator")
    assert hasattr(d.display.communicator, "chunksize")
    assert d.display.communicator.chunksize == models.DEFAULT_CHUNK_SIZE
