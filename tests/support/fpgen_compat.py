"""fpgen 1.3.0's index decoder, made to run on Python 3.15 (P1.22, D.CIB85).

camoufox draws every fingerprint through fpgen, whose `unpacker.base85_to_int`
hands `base64.b85decode` its lookup indices. One index in fpgen's data is a
single character (`'!'`, index 0; the other 12676 are two or three). Python
3.14 decoded a trailing one-character group to no bytes; 3.15 raises
`binascii.Error: Incomplete Base85 group`, so on 3.15 no fingerprint is drawn
and no test browser starts. That is CI's red on main since v0.45.0 (runs
42158445750, 42158513910).

This machine stayed green because its copy of fpgen had been EDITED in place
(user site-packages, `if s == '!': return 0`; its RECORD hash no longer
matches) -- CI installs the published wheel. So the suites decode through
`decode_index` below on every machine, whatever copy is installed, and the
hand edit can no longer make this machine disagree with CI.

`decode_index` keeps 3.14's meaning exactly: a trailing one-character group
carries no byte, so it is dropped. tests/test_fpgen_compat.py pins that against
every index fpgen holds, and goes red when an fpgen release lands, so the
shim is re-examined rather than carried past the bug it covers.
"""

from __future__ import annotations

import base64

#: The fpgen release this shim was written against; a newer one is re-examined.
FPGEN_EXAMINED = "1.3.0"


def decode_index(s: str) -> int:
    """fpgen's base85 lookup index as an int, with Python 3.14's semantics."""
    if len(s) % 5 == 1:
        s = s[:-1]
    return int.from_bytes(base64.b85decode(s), byteorder="big")


def install() -> None:
    """Route fpgen's decoder through `decode_index`. Idempotent."""
    from fpgen import unpacker

    unpacker.base85_to_int = decode_index
