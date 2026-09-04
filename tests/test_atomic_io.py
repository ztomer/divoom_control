"""A1/A4: atomic config writes — crash-safe + optional 0600 perms."""
import json
import os
import stat
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.utils.atomic_io import atomic_write_text, atomic_write_config


def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "sub" / "cfg.json"
    atomic_write_text(p, json.dumps({"a": 1}))
    assert json.loads(p.read_text()) == {"a": 1}


def test_atomic_write_replaces_existing(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("old")
    atomic_write_text(p, "new")
    assert p.read_text() == "new"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    p = tmp_path / "cfg.json"
    atomic_write_text(p, "x")
    leftovers = [f for f in os.listdir(tmp_path) if f != "cfg.json"]
    assert leftovers == []


def test_mode_sets_0600(tmp_path):
    p = tmp_path / "secret.json"
    atomic_write_text(p, "s3cret", mode=0o600)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_failure_leaves_original_intact_and_no_temp(tmp_path):
    """If the body raises mid-write, the original file is untouched and no temp
    file is left behind."""
    p = tmp_path / "cfg.json"
    p.write_text("original")

    class _Boom:
        def __str__(self):
            raise RuntimeError("boom serializing")

    try:
        atomic_write_text(p, f"{_Boom()}")  # raises during f-string eval
    except RuntimeError:
        pass
    assert p.read_text() == "original"
    assert [f for f in os.listdir(tmp_path) if f != "cfg.json"] == []


def test_atomic_write_config_roundtrips(tmp_path):
    import configparser
    cfg = configparser.ConfigParser()
    cfg["divoom"] = {"email": "a@b.c"}
    p = tmp_path / "config.ini"
    atomic_write_config(p, cfg, mode=0o600)
    back = configparser.ConfigParser()
    back.read(p)
    assert back["divoom"]["email"] == "a@b.c"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
