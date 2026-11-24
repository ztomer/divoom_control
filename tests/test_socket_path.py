"""`divoom_client.socket_path`: a socket path that binds whatever TMPDIR is.

The push gate's per-step TMPDIR is 69 bytes deep, which put
`mkdtemp(prefix="divoomd_events_")/daemon.sock` at 104 bytes, one past
`sun_path` (DV.SOCKETFLAKE). These bind a real socket under a base deeper
than `sun_path` itself, so no name could fit there.
"""

from __future__ import annotations

import os
import shutil
import socket

import pytest

from divoom_client import socket_path as sp


@pytest.fixture
def deep_base(tmp_path):
    return str(tmp_path / ("x" * sp.MAX_SOCKET_PATH))


def _binds(path: str) -> None:
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(path)
    finally:
        s.close()
        os.unlink(path)


def test_a_short_base_keeps_its_own_directory():
    assert sp.fitting_socket_path("/tmp", "a.sock") == "/tmp/a.sock"


def test_a_deep_base_still_binds(deep_base):
    p = sp.fitting_socket_path(deep_base, f"dv_path_{os.getpid()}.sock")
    assert len(p) <= sp.MAX_SOCKET_PATH
    _binds(p)


def test_an_over_long_name_is_hashed_and_stays_unique(deep_base):
    long = "n" * sp.MAX_SOCKET_PATH
    a = sp.fitting_socket_path(deep_base, long + "a.sock")
    b = sp.fitting_socket_path(deep_base, long + "b.sock")
    assert len(a) <= sp.MAX_SOCKET_PATH
    assert a != b
    assert a == sp.fitting_socket_path(deep_base, long + "a.sock")


def test_the_scratch_path_fits_whatever_tmpdir_is():
    assert len(sp.scratch_socket_path("dv_scratch_probe.sock")) <= sp.MAX_SOCKET_PATH


def test_a_socket_dir_under_a_deep_base_binds_a_socket_of_its_room(deep_base):
    d = sp.scratch_socket_dir("dv-dir-", base=deep_base)
    try:
        assert os.path.dirname(d) == sp.SHORT_BASE, d
        _binds(os.path.join(d, "x" * (sp.SOCKET_NAME_ROOM - 1)))
    finally:
        shutil.rmtree(d)


def test_a_socket_dir_stays_under_a_base_that_fits(tmp_path):
    base = "/tmp"
    d = sp.scratch_socket_dir("dv-dir-", base=base)
    try:
        assert os.path.dirname(d) == base
    finally:
        shutil.rmtree(d)


def test_a_prefix_too_long_for_any_base_is_refused(deep_base):
    with pytest.raises(ValueError, match="no room"):
        sp.scratch_socket_dir("p" * sp.MAX_SOCKET_PATH, base=deep_base)
