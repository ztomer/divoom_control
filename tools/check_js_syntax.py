#!/usr/bin/env python3
"""check_js_syntax.py — the syntax gate the web UI's JavaScript never had.

P1.14. On 2026-10-20 a stray backtick inside a template literal in
`divoom_gui/web_ui/templates_settings.js` broke the whole Settings tab:
`window.DivoomTemplates` never existed, so the tab rendered empty. Nothing in
this repo noticed. The browser suites load the page, but a file the page
loads and nothing calls is not exercised by any of them, and the house gate
parses the shell scripts and the Python and had no parser for the ~40
JavaScript files the app is made of.

THE RULE, AND WHY IT IS THIS RULE. The unit of checking is the FILE, and the
file is parsed the way a browser parses a `<script src>`: one classic script,
independently of every other file. Two rules follow from the tree's shape,
and both are load-bearing:

  1. The payload of a template literal is NOT code. `templates_settings.js`
     holds HTML between backticks, with `${...}` holes in it. The browser
     parses the holes as JavaScript and leaves the HTML alone, so a checker
     that judged the payload as code would be judging the wrong thing. The
     failure that actually happened was a payload mistake -- a stray backtick
     ended the literal early, and everything after it was read as JavaScript.

  2. The files are NOT concatenated. The browser makes one Script Record per
     `<script src>`, so an error in one file is an error in that file alone.
     Concatenating would hide errors (an unterminated string in file A would
     swallow file B) and invent them (two files that each declare `const x`
     are fine apart and broken together).

TWO READERS, BOTH OF THEM ABLE TO FAIL. The node reader is the authoritative
one, and it uses `vm.Script` -- the Script goal, which is exactly what a
`<script src>` is -- rather than `node --check`. `node --check` is close but
not the same rule, and the difference is not academic: `node --check` parses a
`.js` file with the CommonJS goal (or, on node 22 and later, with the MODULE
goal when the file has ESM syntax), so it ACCEPTS a file with a top-level
`return`, or with `import`, or with top-level `await` -- all three of which a
browser refuses for a classic script, and all three of which would leave the
app with a file that never loads. `node --check` runs as well, because the row
that opened this work names it and because two readers that must agree are
worth more than one; but the verdict is the union, and the browser's rule
decides.

The pure-Python reader (`tools/_js_lex.py`) is the fallback for a machine
with no node. It is a LEXER, not a parser: it catches unterminated literals
and unbalanced brackets -- the class that broke the Settings tab -- and it
cannot tell that `const x = ;` is nonsense, because only an engine builds the
grammar. It runs on EVERY run, never only when node is missing, because a
fallback that is dormant until the day it is needed is a fallback nobody has
ever seen work.

HONEST SCOPE, stated once and in full:

  * The node reader is the real check. It is a full parse of every file.
  * The pure-Python reader is lexical. It fails on: an unterminated string,
    template literal, comment or regex; a bracket that is never closed, is
    closed twice, or is closed by the wrong kind; a `${}` hole that is never
    closed. It does NOT fail on a grammar error such as `const x = ;`.
  * A machine with no node therefore gets a weaker gate, and the report says
    so in those words. A green run that only had the lexical reader is a
    LEXICAL green, and it is printed as one.
  * The gate covers every `.js` file under `divoom_gui/web_ui/`, not only the
    ones `index.html` names: a file the page does not load today may be
    loaded tomorrow, and two of them today (`templates_gallery.js`,
    `templates_hot_channel.js`) are loaded by the test suite rather than by
    the page.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _empty_scope import scope_is_empty  # noqa: E402
from _js_lex import scan  # noqa: E402
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SCOPE = REPO / "divoom_gui" / "web_ui"

# How many findings to print. One broken file can produce a hundred (the
# lexical reader reads everything after the break as code), and a report that
# buries the first finding under a hundred later ones is a report nobody
# reads.
MAX_REPORTED = 12

# The node reader. `vm.Script` parses with the Script goal -- the goal a
# browser's `<script src>` uses -- and says nothing about the payload of a
# template literal, exactly as the browser says nothing about it.
NODE_READER = r"""
const fs = require('fs');
const vm = require('vm');
let bad = 0;
for (const file of process.argv.slice(2)) {
  let source;
  try {
    source = fs.readFileSync(file, 'utf8');
  } catch (err) {
    console.log('UNREADABLE ' + file + ': ' + err.message);
    bad += 1;
    continue;
  }
  try {
    new vm.Script(source, { filename: file });
  } catch (err) {
    const where = err.stack ? String(err.stack).split('\n')[1] || '' : '';
    console.log('SYNTAX ' + file + ': ' + String(err.message).split('\n')[0] + ' ' + where.trim());
    bad += 1;
  }
}
process.exit(bad > 0 ? 1 : 0);
"""


def js_files(root: Path) -> list[Path]:
    """Every JavaScript file the web UI is made of."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.js") if p.is_file())


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a child with its stdin closed, as the house's stdin rule asks."""
    return subprocess.run(
        argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300
    )


def node_findings(files: list[Path], node: str) -> list[str]:
    """Both node readers: the Script goal, and `node --check`."""
    findings: list[str] = []
    script = _run([node, "-e", NODE_READER, *[str(f) for f in files]])
    for line in script.stdout.splitlines():
        if line.strip():
            findings.append(line.strip())
    if script.returncode not in (0, 1):
        findings.append(f"node reader failed to run: {script.stderr.strip()[:400]}")
    for path in files:
        checked = _run([node, "--check", str(path)])
        if checked.returncode != 0:
            detail = (checked.stderr or checked.stdout).strip().splitlines()
            first = detail[0] if detail else "syntax error"
            findings.append(f"SYNTAX {path}: {first}")
    return findings


def lexical_findings(files: list[Path]) -> list[str]:
    """The pure-Python reader: lexical defects only."""
    findings: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8", errors="replace")
        for problem in scan(source):
            findings.append(f"SYNTAX {path}: {problem}")
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_SCOPE
    files = js_files(root)
    if scope_is_empty("js", len(files), unit="JavaScript files"):
        return 1

    node = shutil.which("node")
    findings: list[str] = []
    if node:
        node_problems = node_findings(files, node)
        findings.extend(node_problems)
        if node_problems:
            err(f"[js] node reader — {len(node_problems)} finding(s) in "
                f"{len(files)} files")
        else:
            info(f"[js] node reader — {len(files)} files parse "
                 f"(vm.Script + node --check)")
    else:
        err("[js] node is not installed — only the LEXICAL reader ran. "
            "This is a weaker gate: it catches unterminated literals and "
            "unbalanced brackets, not grammar errors.")

    lexical_problems = lexical_findings(files)
    findings.extend(lexical_problems)
    if lexical_problems:
        err(f"[js] lexical reader — {len(lexical_problems)} finding(s) in "
            f"{len(files)} files")
    else:
        info(f"[js] lexical reader — {len(files)} files are lexically well formed")

    if findings:
        err(f"[js] {len(findings)} problem(s) in {len(files)} JavaScript files")
        for finding in findings[:MAX_REPORTED]:
            info(finding)
        if len(findings) > MAX_REPORTED:
            info(f"... and {len(findings) - MAX_REPORTED} more")
        return 1
    ok(f"[js] OK — {len(files)} JavaScript files parse"
       + ("" if node else " (lexical reader only: node is absent)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
