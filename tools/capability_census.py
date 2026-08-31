#!/usr/bin/env python3
"""capability_census.py — does everything the daemon owns live in the daemon?

**R72 P0.** R70 asked "does the GUI contain a second implementation?" and
answered it with a DENYLIST: five module names plus four PIL patterns, scoped to
`divoom_gui/`. That allowlist is empty and the class is not closed, because a
denylist enumerates forbidden MEANS while the invariant is about ownership of
ENDS. `divoom_auth` and `http.client` walk straight past a gate that stops
`divoom_lib.cloud` and `urllib.request`.

So this does not ban imports. It asks a different question, from the other
direction: **for every capability the daemon owns, is there Python that does
that job itself?**

Both halves are machine-generated on purpose. The two previous passes at this
class used hand-written lists and both missed things:

  OWNED    every match arm in the daemon's socket dispatch and its device_call
           modules -- read out of the Rust, never maintained by hand
  PYTHON   AST over the whole shipped Python surface (divoom_gui, divoom_client,
           scripts), not just divoom_gui/ -- the notification stack was invisible
           to R70 purely because of scope

Two shapes are reported, because the round's two confirmed findings have
different shapes and a census that only knew one would miss the other:

  DIRECT   a call `mod.name(...)` where `mod` is a divoom_lib module and `name`
           is a capability the daemon answers. This is F1: three GUI sites call
           `divoom_lib.divoom_auth.get_cached_credentials()` while the daemon
           answers `get_cached_credentials` and a wrapper already exists.

  WRAPPED  a function whose OWN name is a daemon capability, whose body reaches
           into divoom_lib to do the work. This is F2: `api/tools.py::sync_time`
           builds the payload through `divoom_lib.system.date_time`, and the
           daemon has had `sync_time` all along -- and the Python one was broken.

Exit status is 0 always: this is an inventory, not yet a gate. P5.1 turns it
into one, once the map it produces has a verdict on every row.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _tui import hr, info, ok, section, warn  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUST = REPO / "divoomd" / "src"
PY_SURFACE = (REPO / "divoom_gui", REPO / "divoom_client", REPO / "scripts")

# A match arm is `"name" =>` or `"a" | "b" | "c" =>`, and the arms wrap across
# lines. Catching only the `=>` form would silently drop every alias but the
# last, which is most of the device_call surface.
_ARM_BEFORE = re.compile(r'"([a-z_][a-z_0-9.]*)"\s*(?:\||=>)')
_ARM_AFTER = re.compile(r'\|\s*"([a-z_][a-z_0-9.]*)"')

# divoom_lib subpackages that DO something a daemon owns. `utils.atomic_io` and
# `lifecycle_config` are deliberately absent: writing a config file the client
# owns is a client job, and flagging it would bury the real findings.
OWNED_LIB = (
    "cloud", "divoom_auth", "weather_provider", "media_decoder",
    "system", "display", "tools", "lan_transport", "wall", "hotchannel_config",
)



def row(text: str) -> None:
    """One census finding, on STDOUT.

    The house `err()` writes to stderr, which is right for a gate and wrong
    here: piped through `head` the findings surfaced above the section headers
    that explain them, so the report read as though the tool had crashed.
    """
    print(f"  \u2717 {text}", flush=True)

def daemon_capabilities() -> set[str]:
    """Every command the daemon answers, read from its Rust match arms."""
    caps: set[str] = set()
    files = [RUST / "daemon" / "dispatch.rs"]
    files += sorted((RUST / "device_call").glob("*.rs"))
    for f in files:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        caps |= set(_ARM_BEFORE.findall(text))
        caps |= set(_ARM_AFTER.findall(text))
    # The bare tail of a dotted alias is the name a GUI method would share.
    return caps | {c.rsplit(".", 1)[-1] for c in caps if "." in c}


def _divoom_lib_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> divoom_lib path, for both import spellings."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("divoom_lib"):
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("divoom_lib"):
                    out[a.asname or a.name.split(".")[0]] = a.name
    return out


def _is_owned_lib(path: str) -> bool:
    tail = path[len("divoom_lib."):] if path.startswith("divoom_lib.") else path
    return any(tail == m or tail.startswith(m + ".") for m in OWNED_LIB)


def scan_python(caps: set[str]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """(direct, wrapped, reaches) — Python doing a job the daemon owns.

    The third category exists because the first two match on NAME, and the
    invariant is about the WORK. `media_sync.py` calls
    `divoom_lib.weather_provider._resolve_location(None)` -- weather resolution,
    which the daemon owns -- and neither name-based rule sees it: the function
    is not a daemon command name, and it is bare-imported so there is no
    `mod.attr` to match. A census that reported clean while that stood would be
    measuring its own rules rather than the invariant.

    REACHES is deliberately lower-confidence and listed separately: a call into
    an owned module MIGHT be a pure helper. It is a read-and-decide list, not an
    accusation.
    """
    direct: list[tuple] = []
    wrapped: list[tuple] = []
    reaches: list[tuple] = []
    for root in PY_SURFACE:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            aliases = _divoom_lib_aliases(tree)
            owned_aliases = {k: v for k, v in aliases.items() if _is_owned_lib(v)}
            rel = path.relative_to(REPO)

            # DIRECT: mod.capability(...) — and REACHES for everything else
            # that calls into an owned module.
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                        and fn.value.id in owned_aliases):
                    where = f"{rel}:{node.lineno}"
                    lib = owned_aliases[fn.value.id]
                    if fn.attr in caps:
                        direct.append((where, fn.attr, lib))
                    else:
                        reaches.append((where, f"{fn.value.id}.{fn.attr}", lib))
                elif isinstance(fn, ast.Name) and fn.id in owned_aliases:
                    # `from divoom_lib.weather_provider import _resolve_location`
                    # then `_resolve_location(...)` — no attribute to match on.
                    reaches.append((f"{rel}:{node.lineno}", fn.id,
                                    owned_aliases[fn.id]))

            # WRAPPED: def <capability>(...) whose body reaches into divoom_lib
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name not in caps:
                    continue
                local = _divoom_lib_aliases(fn)
                used = {k: v for k, v in local.items() if _is_owned_lib(v)}
                used |= {k: v for k, v in owned_aliases.items()
                         if any(isinstance(n, ast.Name) and n.id == k
                                for n in ast.walk(fn))}
                if used:
                    wrapped.append((f"{rel}:{fn.lineno}", fn.name,
                                    ", ".join(sorted(set(used.values())))))
    return direct, wrapped, reaches


def main() -> int:
    caps = daemon_capabilities()
    section("capability census")
    info(f"daemon owns {len(caps)} command names "
         f"(socket dispatch + device_call match arms)")

    direct, wrapped, reaches = scan_python(caps)

    section("DIRECT — Python calling a daemon capability through divoom_lib")
    if direct:
        for where, name, lib in sorted(direct):
            row(f"{name}()  <- {where}  via {lib}")
    else:
        ok("none")

    section("WRAPPED — a daemon capability reimplemented over divoom_lib")
    if wrapped:
        for where, name, libs in sorted(wrapped):
            row(f"{name}()  <- {where}  uses {libs}")
    else:
        ok("none")

    section("REACHES — a call into an owned module, name not a command")
    if reaches:
        for where, name, lib in sorted(reaches):
            row(f"{name}()  <- {where}  in {lib}")
    else:
        ok("none")

    hr()
    named = len(direct) + len(wrapped)
    total = named + len(reaches)
    (warn if total else ok)(
        f"{total} site(s): {len(direct)} DIRECT, {len(wrapped)} WRAPPED, "
        f"{len(reaches)} REACHES")
    info(f"{named} match a daemon command by NAME and are the confident set;")
    info("REACHES is read-and-decide — a call into an owned module might be a")
    info("pure helper, or might be the whole point (weather resolution and the")
    info("hotchannel config both turned up there, and both are real).")
    info("Inventory only — P5.1 turns this into a gate once every row has a")
    info("verdict in docs/CAPABILITY_MAP.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
