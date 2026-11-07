"""The fpgen decoder shim (tests/support/fpgen_compat.py; P1.22, D.CIB85)."""

from __future__ import annotations

import base64
import binascii
import importlib.metadata

import pytest

from tests.support import fpgen_compat

_ALPHABET = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~"


def _decode_314(s: str) -> int:
    """Python 3.14's b85decode, written out: pad the last group with '~', drop the pad bytes."""
    pad = -len(s) % 5
    raw = s.encode() + b"~" * pad
    out = bytearray()
    for i in range(0, len(raw), 5):
        acc = 0
        for c in raw[i : i + 5]:
            acc = acc * 85 + _ALPHABET.index(c)
        out += acc.to_bytes(4, "big")
    return int.from_bytes(bytes(out[: len(out) - pad]), "big")


@pytest.mark.parametrize("s", ["!", "0", "00", "0~", "zz", "VPRom", "VPRomV", "VPRomVP"])
def test_the_shim_decodes_as_python_314_did(s: str) -> None:
    assert fpgen_compat.decode_index(s) == _decode_314(s)


def test_the_interpreter_still_refuses_a_one_character_group() -> None:
    """The shim's reason. If a Python accepts '!' again, the shim may be retired."""
    with pytest.raises(binascii.Error):
        base64.b85decode("!")


def test_every_index_fpgen_holds_decodes_and_resolves() -> None:
    """Against the real data, not a sample: each index decodes as 3.14 did and names a value."""
    pytest.importorskip("fpgen")
    fpgen_compat.install()
    from fpgen import unpacker
    from fpgen.utils import NETWORK

    indices = {v for node in NETWORK.nodes_by_name.values() for v in node.possible_values}
    assert "!" in indices, "fpgen's data no longer holds the one-character index; re-examine the shim"
    for s in indices:
        n = fpgen_compat.decode_index(s)
        assert n == _decode_314(s)
        assert 0 <= n < len(unpacker.VALUE_PAIRS)
    assert unpacker.base85_to_int is fpgen_compat.decode_index


def test_a_new_fpgen_release_reexamines_the_shim() -> None:
    try:
        version = importlib.metadata.version("fpgen")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("fpgen is not installed (the [e2e] extra)")
    assert version == fpgen_compat.FPGEN_EXAMINED, (
        f"fpgen {version} is installed; the shim was written for {fpgen_compat.FPGEN_EXAMINED}. "
        "If the new release decodes '!' on this Python, delete tests/support/fpgen_compat.py; "
        "else move FPGEN_EXAMINED."
    )


def test_the_launch_seam_installs_the_shim() -> None:
    pytest.importorskip("camoufox.utils")
    from fpgen import unpacker

    from tests.support.browser_options import launch_options_for

    unpacker.base85_to_int = lambda s: (_ for _ in ()).throw(AssertionError("unshimmed"))
    launch_options_for(network=False, launching=False)
    assert unpacker.base85_to_int is fpgen_compat.decode_index
