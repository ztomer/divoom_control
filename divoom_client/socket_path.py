"""A unix-socket path that fits in ``sockaddr_un``, wherever the temp dir is.

The Python twin of ``divoomd/src/socket_path.rs``. ``sun_path`` holds 104 bytes
on macOS (108 on Linux), and the temp dir is whatever the environment says: a
push gate gives each step its own ``TMPDIR`` under
``/var/folders/.../T/goh.noindex/step.NN/`` (69 bytes before a name), so a
socket named under it binds on a laptop and is refused in the gate
("the socket path is 104 characters; this platform allows 103",
DV.SOCKETFLAKE). Every caller that makes a socket under a temp dir asks here.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

#: Longest usable ``sun_path`` minus the NUL, as ``socket_bind::MAX_SOCKET_PATH``.
MAX_SOCKET_PATH = 103 if sys.platform == "darwin" else 107

#: Room a socket inside a :func:`scratch_socket_dir` may use: ``/`` and 15 bytes.
SOCKET_NAME_ROOM = 16

#: The short base used when the temp dir is too deep: always present, and short.
SHORT_BASE = "/tmp"

#: ``mkdtemp`` appends this many random characters to its prefix.
_MKDTEMP_RANDOM = 8


def _fits(path: str, room: int = 0) -> bool:
    return len(os.fsencode(path)) + room <= MAX_SOCKET_PATH


def fitting_socket_path(base: str, name: str) -> str:
    """``base/name`` when it fits; else ``/tmp/name``; else a hashed name under ``/tmp``."""
    wanted = os.path.join(base, name)
    if _fits(wanted):
        return wanted
    short = os.path.join(SHORT_BASE, name)
    if _fits(short):
        return short
    digest = hashlib.sha256(os.fsencode(wanted)).hexdigest()[:16]
    return os.path.join(SHORT_BASE, f"divoom_{digest}.sock")


def scratch_socket_path(name: str) -> str:
    """:func:`fitting_socket_path` under this process's temp dir."""
    return fitting_socket_path(tempfile.gettempdir(), name)


def scratch_socket_dir(prefix: str, base: str | None = None) -> str:
    """A fresh ``mkdtemp`` directory for sockets named in at most :data:`SOCKET_NAME_ROOM` bytes.

    Made under ``base`` (the temp dir by default) when such a socket fits, else
    under ``/tmp``. The caller owns it and removes it, as with ``mkdtemp``.
    """
    base = tempfile.gettempdir() if base is None else base
    for where in (base, SHORT_BASE):
        if _fits(os.path.join(where, prefix + "x" * _MKDTEMP_RANDOM), SOCKET_NAME_ROOM):
            return tempfile.mkdtemp(prefix=prefix, dir=where)
    raise ValueError(f"prefix {prefix!r} leaves no room for a socket even under {SHORT_BASE}")
