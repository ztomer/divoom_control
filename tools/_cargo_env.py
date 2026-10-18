"""_cargo_env.py — the environment for a cargo build of a throwaway probe crate.

A tool that compiles a scratch crate (`render_tray_icon.py --verify-against-rust`,
`mem_gauge_compare.py`) owns a directory and removes it, or reuses it, as its
own. Cargo does not keep its intermediates there unless told to: the house
`~/.cargo/config.toml` sets

    build-dir = "{cargo-cache-home}/build/{workspace-path-hash}"

so the build of a crate in a FRESH temp dir lands in a fresh directory under
`~/.cargo/build` that nothing ever collects. The tray-icon verifier left 112 of
them (all fingerprint `probe-b31fe2907f4634b8`) before this existed: removing the
temp dir removed the source and the final binary, never the build.

`probe_env(root)` puts both of cargo's directories INSIDE `root`, so whatever
removes `root` removes the build with it. The environment variables outrank
every config file, which is the point. A caller that set its own
`CARGO_BUILD_BUILD_DIR` / `CARGO_TARGET_DIR` (a gate that owns a build root and
cleans it, say) is left alone: that caller already decided where builds go.
"""
from __future__ import annotations

import os
from pathlib import Path


def probe_env(root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """`base` (default: this process's environment) with cargo's build and
    target directories inside `root`, unless `base` already names them."""
    env = dict(os.environ if base is None else base)
    for var, sub in (("CARGO_BUILD_BUILD_DIR", "build"), ("CARGO_TARGET_DIR", "target")):
        # An empty value names nothing; cargo would fall back to the config.
        if not env.get(var):
            env[var] = str(root / sub)
    return env
