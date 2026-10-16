"""P1.12: the framing-vector generator runs, and reproduces the pinned file exactly.

After phase L4 deleted the Python encoders with the C library,
`scripts/codegen/gen_framing_vectors.py` could not run at all — it called
`framing.encode_basic_payload`, which no longer exists — so the committed
`divoomd/tests/framing_vectors.json` could never be regenerated, while
`tests/test_framing_vectors.py` still told the reader to regenerate it.

The generator now owns only what Python still owns: the PARSER's expected
output for inputs frozen in the committed file, with the encode vectors carried
forward as the C library's frozen record. This test is the contract — `build()`
reproduces the committed document and `render()` reproduces its exact bytes, so
running the generator can never silently rewrite the vectors.
"""

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.append(str(REPO))

GENERATOR = REPO / "scripts" / "codegen" / "gen_framing_vectors.py"
VECTORS = REPO / "divoomd" / "tests" / "framing_vectors.json"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_framing_vectors", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_reproduces_the_committed_vectors():
    built = _load_generator().build(VECTORS)
    assert built == json.loads(VECTORS.read_text()), (
        "the generator no longer reproduces framing_vectors.json"
    )


def test_generator_renders_the_committed_file_byte_for_byte():
    module = _load_generator()
    assert module.render(module.build(VECTORS)) == VECTORS.read_text(), (
        "the generator's rendered output differs from the committed file byte for byte"
    )
