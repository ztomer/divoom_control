"""The daemon's bind-failure report, as the client and GUI consume it.

The behaviour under test is "the user finds out WHY". Before this, a daemon that
refused to bind exited with its explanation on stderr, which the GUI redirects
to a log file, and the client reported only that it had run out of patience.
"""
from __future__ import annotations

import json
import os

import pytest

from divoom_client.socket_failure import (
    SocketFailure,
    clear_socket_failure,
    explain_daemon_failure,
    failure_path,
    read_socket_failure,
)


@pytest.fixture()
def sock(tmp_path):
    return str(tmp_path / "divoom.sock")


def write_report(sock: str, body: str) -> None:
    with open(failure_path(sock), "w", encoding="utf-8") as fh:
        fh.write(body)


def test_reads_reason_remedy_and_transience(sock):
    write_report(sock, "reason: /x is a directory, not a socket\n"
                       "remedy: Move it yourself.\n"
                       "transient: false\n")
    f = read_socket_failure(sock)
    assert f == SocketFailure(
        reason="/x is a directory, not a socket",
        remedy="Move it yourself.",
        transient=False,
    )


def test_transient_is_parsed(sock):
    write_report(sock, "reason: starting up\nremedy: wait\ntransient: true\n")
    f = read_socket_failure(sock)
    assert f is not None and f.transient is True


def test_absent_report_is_none_not_an_error(sock):
    # The normal case, and also "the daemon never got far enough to write one".
    assert read_socket_failure(sock) is None


def test_a_reason_containing_a_colon_survives(sock):
    # Reasons quote paths and errnos, both of which contain colons.
    write_report(sock, "reason: permission denied for /x: Operation not permitted\n"
                       "remedy: Delete it as that user.\n")
    f = read_socket_failure(sock)
    assert f is not None
    assert f.reason == "permission denied for /x: Operation not permitted"


def test_malformed_report_is_none_rather_than_blank(sock):
    # A blank explanation is worse than an honest "unknown": it looks like an
    # answer. The caller's fallback must win instead.
    write_report(sock, "garbage with no fields\n")
    assert read_socket_failure(sock) is None


def test_empty_reason_is_rejected(sock):
    write_report(sock, "reason:\nremedy: something\n")
    assert read_socket_failure(sock) is None


def test_message_joins_reason_and_remedy(sock):
    f = SocketFailure(reason="a stale socket", remedy="Try again.", transient=True)
    assert f.message() == "a stale socket. Try again."


def test_message_without_a_remedy_is_just_the_reason():
    f = SocketFailure(reason="a stale socket", remedy="", transient=False)
    assert f.message() == "a stale socket"


def test_explain_falls_back_when_nothing_was_reported(sock):
    assert explain_daemon_failure(sock, "no reason reported") == "no reason reported"


def test_explain_prefers_the_daemons_own_words(sock):
    write_report(sock, "reason: /x is a regular file, not a socket\n"
                       "remedy: Move it.\n")
    out = explain_daemon_failure(sock, "no reason reported")
    assert "regular file" in out and "Move it." in out


def test_clear_removes_the_report(sock):
    write_report(sock, "reason: x\n")
    clear_socket_failure(sock)
    assert not os.path.exists(failure_path(sock))
    clear_socket_failure(sock)  # idempotent


def test_daemon_health_carries_the_reason_to_the_banner(monkeypatch, sock):
    """The GUI's banner is where a user actually looks."""
    from divoom_gui import scanner_mixin

    monkeypatch.delenv("DIVOOM_DAEMON_HOST", raising=False)
    monkeypatch.setattr("divoom_gui.daemon_bridge.daemon_alive", lambda *a, **k: False)
    monkeypatch.setattr("divoom_client.daemon_protocol.DEFAULT_SOCKET_PATH", sock)
    write_report(sock, "reason: /x is a directory, not a socket\n"
                       "remedy: Move or delete that file yourself.\n"
                       "transient: false\n")

    class Probe(scanner_mixin.ScannerMixin):
        pass

    out = json.loads(Probe().daemon_health())
    assert out["daemon"] is False
    assert "directory" in out["reason"]
    assert "Move or delete" in out["remedy"]


def test_daemon_health_still_reports_liveness_without_a_report(monkeypatch, sock):
    # Diagnosis is a bonus; it must never break the liveness answer the banner
    # depends on.
    from divoom_gui import scanner_mixin

    monkeypatch.delenv("DIVOOM_DAEMON_HOST", raising=False)
    monkeypatch.setattr("divoom_gui.daemon_bridge.daemon_alive", lambda *a, **k: False)
    monkeypatch.setattr("divoom_client.daemon_protocol.DEFAULT_SOCKET_PATH", sock)

    class Probe(scanner_mixin.ScannerMixin):
        pass

    out = json.loads(Probe().daemon_health())
    assert out == {"daemon": False}
