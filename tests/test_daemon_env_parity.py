"""The daemon env contract, pinned on both sides of the language boundary.

The CLI hands work to `divoomd` by writing the daemon target into the
environment and then `execv`ing: `--host`/`--port`/`--token`/`--socket` become
`DIVOOM_DAEMON_HOST`/`_PORT`/`_TOKEN` and `DIVOOM_SOCKET`, which
`DaemonTarget::from_env` reads on the Rust side. That handoff has no return
value, so a name that exists on only one side does not fail — it silently falls
back to a default socket, which on a user's machine is either a confusing "not
reachable" or the WRONG daemon.

These are the names the handoffs depend on. They are strings in two languages,
so something has to compare them, and it should be a test rather than a comment.
The Rust side is read out of the source because these are compile-time string
literals, not an exported constant.
"""
from __future__ import annotations

import re
from pathlib import Path

from divoom_client.daemon_protocol import ENV_HOST, ENV_PORT, ENV_SOCKET, ENV_TOKEN

REPO_ROOT = Path(__file__).resolve().parent.parent
RUST_TARGET = REPO_ROOT / "divoomd" / "src" / "daemon_target.rs"


def _rust_env_names() -> set[str]:
    source = RUST_TARGET.read_text(encoding="utf-8")
    return set(re.findall(r'std::env::var\("([A-Z_]+)"\)', source))


def test_every_python_env_name_is_one_the_rust_client_reads() -> None:
    rust = _rust_env_names()
    missing = [name for name in (ENV_HOST, ENV_PORT, ENV_TOKEN, ENV_SOCKET) if name not in rust]
    assert not missing, (
        f"the Python client writes {missing} but divoomd's DaemonTarget::from_env "
        f"does not read them; a handoff would silently use the default socket. "
        f"It reads: {sorted(rust)}"
    )


def test_the_socket_name_is_the_one_the_daemon_target_documents() -> None:
    # Cheap, and it catches the specific regression this file exists for: the
    # socket name drifting to a second literal in cli_commands.py.
    source = (REPO_ROOT / "divoom_lib" / "cli_commands.py").read_text(encoding="utf-8")
    bare = re.findall(r'"(DIVOOM_[A-Z_]+)"', source)
    assert not bare, (
        f"use the ENV_* constants from divoom_client.daemon_protocol, not bare "
        f"literals: {bare}"
    )


def test_the_defaults_the_two_sides_fall_back_to_are_the_same_path() -> None:
    """Both fall back to `/tmp/divoom.sock` when nothing is set.

    A silent divergence here is invisible until a user runs a bare `divoomd` (no
    `--socket`) and every client then reports the daemon as down, because the
    binary served one path and the clients looked at another.
    """
    from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH

    rust = RUST_TARGET.read_text(encoding="utf-8")
    assert DEFAULT_SOCKET_PATH in rust, (
        f"Python falls back to {DEFAULT_SOCKET_PATH} but daemon_target.rs does not "
        f"name that path; the two defaults have diverged"
    )
    # The binary's own serve default is a DIFFERENT constant (cli_args.rs), which
    # is the trap: a bare `divoomd` serves /tmp/divoomd.sock while every client
    # looks at /tmp/divoom.sock. Pinned here so the divergence is a recorded
    # fact rather than something a session has to rediscover.
    cli_args = (REPO_ROOT / "divoomd" / "src" / "cli_args.rs").read_text(encoding="utf-8")
    serve_default = re.search(r'DEFAULT_SOCKET_PATH: &str = "([^"]+)"', cli_args)
    assert serve_default is not None, "cli_args.rs no longer declares its default socket"
    assert serve_default.group(1) == DEFAULT_SOCKET_PATH, (
        f"divoomd serves {serve_default.group(1)} by default but every client looks "
        f"at {DEFAULT_SOCKET_PATH}: a bare `divoomd` would be invisible to them"
    )
