"""_srcscan.py — shared source-text scanning helpers for the repo's gates.

Several gates find facts by running regexes over Rust source. Source text does
not distinguish CODE from a COMMENT THAT QUOTES CODE, and that is not a
hypothetical: `check_positional_args.py` flagged `display.show_light` because
the handler carries a comment explaining that brightness "used to read
`args.get(1)`" before it was fixed. The gate matched its own description of the
bug it exists to catch, and reported the corrected handler as broken.

Any gate that regexes Rust source shares that exposure — a commented-out
`(113, WeatherType::Clear)` would be read as a live table entry — so the
stripper lives here once instead of being re-derived per gate.
"""
from __future__ import annotations

import re

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def strip_rust_comments(src: str) -> str:
    """Blank out Rust comments, preserving every byte offset and newline.

    Blanking rather than deleting keeps offsets into the original text valid
    (callers index back into it) and removes any brace inside a comment, which
    would otherwise corrupt brace-depth scanning.

    String literals are deliberately LEFT ALONE: gates key on literals such as
    `"display.show_light" =>` to identify match arms.
    """
    return _COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
