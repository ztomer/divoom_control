"""tools/check_socket_paths.py refuses a socket named on a raw temp dir."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_socket_paths", REPO / "tools" / "check_socket_paths.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_rust_temp_dir_join_across_lines_is_refused():
    src = 'let p = std::env::temp_dir()\n    .join(format!("d_{}.sock", 1));\n'
    assert gate.rust_findings("x.rs", src)


def test_rust_helper_call_passes():
    src = 'let p = divoomd::socket_path::scratch_socket_path(&format!("d_{}.sock", 1));\n'
    assert not gate.rust_findings("x.rs", src)


def test_python_mkdtemp_variable_then_join_is_refused():
    src = 'd = tempfile.mkdtemp(prefix="x")\nsock = os.path.join(d, "d.sock")\n'
    assert gate.python_findings("x.py", src) == [
        "x.py:2: a socket named under the temp dir -- use divoom_client.socket_path"
    ]


def test_python_same_line_gettempdir_is_refused():
    assert gate.python_findings("x.py", 'p = os.path.join(tempfile.gettempdir(), "a.sock")\n')


def test_python_helper_and_comments_pass():
    src = 'd = scratch_socket_dir("x")\nsock = os.path.join(d, "d.sock")\n# mkdtemp() and "a.sock" in prose\n'
    assert not gate.python_findings("x.py", src)


def test_the_tree_is_clean():
    assert gate.main() == 0
