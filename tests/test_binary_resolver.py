"""The daemon/menubar binary is chosen by VERSION, never by location or mtime.

Every test here is written against the concrete way the old code failed, because
each of those was green under the previous rules:

* `spawn_daemon` walked ``["release", "debug"]`` and took the first that
  existed, so a stale `target/release/divoomd` won unconditionally;
* `tests/support/daemon_binary.py` picked newest-by-mtime, so a stale binary
  won whenever it happened to be the newest one;
* neither could ASK a binary its version, because `divoomd --version` started a
  daemon instead of answering.

`stub_binary` writes a shell script that behaves like a given divoomd — which
means the timeout case is exercised by a stub that HANGS the way a
pre-`--version` binary does, not by a mock that returns None.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from divoom_client import binary_resolver


def stub_binary(path: Path, *, prints: str | None = None, exit_code: int = 0,
                hangs: bool = False) -> Path:
    """A fake divoomd. `hangs=True` models a binary too old to have --version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if hangs:
        body = "sleep 30\n"
    else:
        body = ""
        if prints is not None:
            body += f"echo {prints!r}\n"
        body += f"exit {exit_code}\n"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A fake repo root whose target/{release,debug} we control."""
    monkeypatch.setattr(binary_resolver, "REPO_ROOT", tmp_path)
    # Bundle lookups must not leak the real environment into these tests.
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    return tmp_path


# ── binary_version ────────────────────────────────────────────────────────────

def test_version_is_read_from_the_binarys_own_output(tmp_path):
    b = stub_binary(tmp_path / "divoomd", prints="divoomd 0.28.2")
    assert binary_resolver.binary_version(b) == "0.28.2"


def test_a_binary_that_exits_nonzero_reports_no_version(tmp_path):
    b = stub_binary(tmp_path / "divoomd", prints="divoomd 0.28.2", exit_code=1)
    assert binary_resolver.binary_version(b) is None


def test_unparseable_output_reports_no_version(tmp_path):
    b = stub_binary(tmp_path / "divoomd", prints="listening on /tmp/divoomd.sock")
    assert binary_resolver.binary_version(b) is None


def test_a_binary_too_old_for_the_flag_is_killed_and_reports_no_version(tmp_path):
    """The pre-`--version` behaviour: ignore the flag and start serving.

    This is the case the timeout exists for. Without the kill, every probe of an
    old binary would leak a running daemon.
    """
    b = stub_binary(tmp_path / "divoomd", hangs=True)
    assert binary_resolver.binary_version(b, timeout=1.0) is None


def test_the_probe_never_touches_the_default_socket(tmp_path):
    """A hung probe is SIGKILLed, so it cannot clean up after itself.

    The probe therefore passes `--socket` to a throwaway path: an old binary
    binds that instead of `/tmp/divoomd.sock`, and the litter dies with the temp
    directory. This asserts the flag is actually passed, since the consequence
    of dropping it is a stale socket in the real default location.
    """
    b = tmp_path / "divoomd"
    log = tmp_path / "argv.txt"
    b.write_text(f'#!/bin/sh\necho "$@" > {log}\necho "divoomd 0.28.2"\n')
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    binary_resolver.binary_version(b)
    argv = log.read_text()
    assert "--socket" in argv
    assert "/tmp/divoomd.sock" not in argv


def test_the_menubar_is_probed_without_a_socket_argument(tmp_path):
    """The socket redirect is divoomd's, and giving it to the menubar breaks it.

    divoom-menubar binds no socket and refuses trailing arguments after
    `--version` — a lone flag is the whole request, since the agent takes no
    configuration. Appending `--socket` there turns a version probe into an
    exit-2, which the resolver reads as "stale". Caught by the gate on the first
    run after the flag landed; pinned here so a generic probe cannot creep back.
    """
    b = tmp_path / "divoom-menubar"
    log = tmp_path / "argv.txt"
    b.write_text(f'#!/bin/sh\necho "$@" > {log}\necho "divoom-menubar 0.28.3"\n')
    b.chmod(b.stat().st_mode | stat.S_IEXEC)

    assert binary_resolver.binary_version(b) == "0.28.3"
    assert log.read_text().strip() == "--version"


# ── resolve ───────────────────────────────────────────────────────────────────

def test_the_matching_version_wins_over_the_newer_stale_one(tree, monkeypatch):
    """The regression, stated exactly.

    `release` is BOTH the location the old client preferred and the newest file
    on disk, so it wins under either of the two superseded rules. It is stale,
    so it must lose.
    """
    stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.28.2")
    rel = stub_binary(tree / "target" / "release" / "divoomd", prints="divoomd 0.27.0")
    os.utime(rel, (2 ** 31 - 1, 2 ** 31 - 1))  # newest by a wide margin
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.2")

    assert binary_resolver.resolve("divoomd") == tree / "target" / "debug" / "divoomd"


def test_no_current_binary_resolves_to_none_rather_than_a_stale_one(tree, monkeypatch):
    """Returning the stale binary is what produced the spawn/kill/respawn loop:
    the client would start it, notice the mismatch, stop it, and start it again.
    """
    stub_binary(tree / "target" / "release" / "divoomd", prints="divoomd 0.27.0")
    stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.26.0")
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.2")

    assert binary_resolver.resolve("divoomd") is None


def test_an_unknowable_expectation_falls_back_to_recency(tree, monkeypatch):
    """An unknown expectation is not evidence of a problem, so it must not stop
    a daemon that may be perfectly current."""
    old = stub_binary(tree / "target" / "release" / "divoomd", prints="divoomd 0.27.0")
    new = stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.26.0")
    os.utime(old, (1, 1))
    os.utime(new, (2 ** 31 - 1, 2 ** 31 - 1))
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: None)

    assert binary_resolver.resolve("divoomd") == new


def test_an_explicit_override_is_not_second_guessed(tree, monkeypatch):
    b = stub_binary(tree / "elsewhere" / "divoomd", prints="divoomd 0.1.0")
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.2")
    assert binary_resolver.resolve("divoomd", override=str(b)) == b


def test_an_override_pointing_nowhere_is_discarded_and_resolution_continues(tree, monkeypatch):
    """Long-standing documented behaviour: `DIVOOM_RUST_BINARY` left over from a
    moved checkout must not brick the app.

    Broken once already — the first version of `resolve` returned None on a
    missing override, which turned a stale environment variable into "divoomd
    binary not found" with a perfectly good binary sitting in target/.
    """
    good = stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.28.3")
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.3")

    assert binary_resolver.resolve("divoomd", override="/nope/divoomd") == good


def test_a_missing_override_with_nothing_built_resolves_to_none(tree):
    assert binary_resolver.resolve("divoomd", override="/nope/divoomd") is None


def test_a_bundled_binary_wins_over_the_dev_tree(tree, monkeypatch, tmp_path):
    """Inside a packaged app the answer comes from the BUNDLE, full stop.

    Falling out of a shipped .app into a developer's target/ would run a daemon
    the bundle was never built with. Also broken once: version-matching across
    one flat candidate list sent an unprobeable bundled binary to the dev tree.
    """
    bundle = tmp_path / "bundle"
    bundled = stub_binary(bundle / "bin" / "divoomd", prints="divoomd 0.28.3")
    stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.28.3")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.3")

    assert binary_resolver.resolve("divoomd") == bundled


def test_an_unverifiable_bundled_binary_is_used_rather_than_the_dev_tree(
        tree, monkeypatch, tmp_path):
    """"Rebuild" is not an action available to someone running an installed app.

    So a bundle whose version cannot be confirmed is still the right answer:
    refusing to start is worse than starting the only daemon that shipped, and
    reaching into target/ instead would be actively wrong. The build-time gate
    is what keeps that binary honest.
    """
    bundle = tmp_path / "bundle"
    bundled = stub_binary(bundle / "bin" / "divoomd", prints="not a version line")
    stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.28.3")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.3")

    assert binary_resolver.resolve("divoomd") == bundled


def test_nothing_built_resolves_to_none(tree):
    assert binary_resolver.resolve("divoomd") is None


# ── stale_report ──────────────────────────────────────────────────────────────

def test_stale_report_names_the_binary_and_what_it_claims(tree, monkeypatch):
    stub_binary(tree / "target" / "release" / "divoomd", prints="divoomd 0.27.0")
    stub_binary(tree / "target" / "debug" / "divoomd", prints="divoomd 0.28.2")
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: "0.28.2")

    report = binary_resolver.stale_report("divoomd")
    assert report == [(tree / "target" / "release" / "divoomd", "0.27.0")]


def test_stale_report_is_empty_when_the_expectation_is_unknown(tree, monkeypatch):
    stub_binary(tree / "target" / "release" / "divoomd", prints="divoomd 0.27.0")
    monkeypatch.setattr(binary_resolver, "_expected_version", lambda: None)
    assert binary_resolver.stale_report("divoomd") == []


# ── the real binaries, and the gate over them ─────────────────────────────────

REPO = Path(__file__).resolve().parent.parent


def _load_gate():
    """Load `tools/check_built_binaries.py` BY PATH, not by `import tools.…`.

    `tools/` is a bare directory with no `__init__.py`, and `divoom_lib/tools/`
    IS a real package. Whichever of the two `import tools` resolves to depends
    on what else has touched `sys.path` earlier in the run — so the import
    worked when this file ran alone and raised ModuleNotFoundError in the full
    suite. Addressing the file directly has no such ambiguity.
    """
    import importlib.util

    path = REPO / "tools" / "check_built_binaries.py"
    spec = importlib.util.spec_from_file_location("_gate_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", binary_resolver.PRODUCT_BINARIES)
def test_the_real_binaries_answer_version_without_starting(name):
    """`--version` must PRINT AND EXIT.

    It used to fall through divoomd's parser and start a daemon on the default
    socket, which is why nothing could cheaply ask a binary what it was. A
    generous timeout here still fails long before a served daemon would return.
    """
    built = binary_resolver.built_candidates(name)
    if not built:
        pytest.skip(f"{name} not built. Run: cargo build -p {name}")
    proc = subprocess.run([str(built[0]), "--version"], capture_output=True,
                          text=True, timeout=15, stdin=subprocess.DEVNULL)
    assert proc.returncode == 0
    assert proc.stdout.startswith(f"{name} "), proc.stdout


@pytest.mark.parametrize("name", binary_resolver.PRODUCT_BINARIES)
def test_the_real_binaries_reject_an_unknown_argument(name):
    """A typo used to be silently ignored, so `--sokcet /tmp/x` served the
    DEFAULT socket while looking like it had been told otherwise."""
    built = binary_resolver.built_candidates(name)
    if not built:
        pytest.skip(f"{name} not built. Run: cargo build -p {name}")
    proc = subprocess.run([str(built[0]), "--definitely-not-a-flag"],
                          capture_output=True, text=True, timeout=15,
                          stdin=subprocess.DEVNULL)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    # The two binaries word it differently on purpose — divoomd rejects the one
    # argument it could not place, the menubar rejects the whole argv because it
    # accepts no configuration at all. Both must NAME what they refused, which
    # is the part that matters to whoever typed it.
    assert "--definitely-not-a-flag" in proc.stderr
    assert "--help" in proc.stderr


def test_the_gate_passes_on_this_tree():
    proc = subprocess.run([sys.executable, "tools/check_built_binaries.py"],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_gate_fails_when_a_built_binary_is_stale(tmp_path, monkeypatch):
    """Proof the gate BITES, driven through its own module rather than by
    deleting a real binary.

    A gate nobody has watched fail is a gate you are only assuming works — and
    this one's whole job is to notice a condition that looked green for two
    releases.
    """
    monkeypatch.setattr(binary_resolver, "REPO_ROOT", tmp_path)
    stub_binary(tmp_path / "target" / "release" / "divoomd", prints="divoomd 0.27.0")

    gate = _load_gate()
    monkeypatch.setattr(gate, "expected_daemon_version", lambda: "0.28.2")
    assert gate.main() == 1


def test_the_gate_skips_rather_than_fails_when_nothing_is_built(tmp_path, monkeypatch):
    """CI builds only what a job needs, and a fresh checkout has nothing. Failing
    there would fire the gate on the absence of a problem."""
    monkeypatch.setattr(binary_resolver, "REPO_ROOT", tmp_path)

    gate = _load_gate()
    monkeypatch.setattr(gate, "expected_daemon_version", lambda: "0.28.2")
    assert gate.main() == 0
