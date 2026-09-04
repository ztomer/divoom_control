"""Atomic file writes — never leave a truncated/corrupt config on a crash.

A1: most config writers used in-place writes (``open(w)`` / ``write_text`` /
``json.dump``), so a crash or power-loss mid-write truncated the file and lost
that config on next launch (credentials, presets, alarms, wall slots, routing,
…). This helper writes a temp file in the SAME directory, fsyncs it, then
``os.replace()`` over the target — an atomic rename, so a reader always sees
either the old file or the complete new one, never a partial write.

A4: ``mode`` (e.g. ``0o600``) restricts permissions for files holding secrets
(the cloud password in ``config.ini``, the auth token cache).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path, text: str, *, encoding: str = "utf-8",
                      mode: int | None = None) -> None:
    """Atomically write ``text`` to ``path`` (temp-in-same-dir + ``os.replace``).

    ``mode`` is an optional octal permission (e.g. ``0o600``) applied to the file
    before it is moved into place — use it for credential/token files.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_config(path, parser, *, mode: int | None = None) -> None:
    """Atomically persist a ``configparser.ConfigParser`` (render to a string
    first, then :func:`atomic_write_text`)."""
    import io
    buf = io.StringIO()
    parser.write(buf)
    atomic_write_text(path, buf.getvalue(), mode=mode)
