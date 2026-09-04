import json
import os
from pathlib import Path

DEFAULT_CACHE_DIR = os.path.join(
    os.path.expanduser("~"), ".divoom-control", "cache")

def ensure_cache_dir(cache_dir: str) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

def device_cache_path(cache_dir: str, device_id: str) -> str:
    # Sanitize device id for filesystem (replace ':' with '_')
    safe_id = device_id.replace(':', '_')
    return os.path.join(cache_dir, f"{safe_id}.json")

def load_device_cache(cache_dir: str, device_id: str) -> dict | None:
    p = device_cache_path(cache_dir, device_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

def save_device_cache(cache_dir: str, device_id: str, data: dict) -> None:
    ensure_cache_dir(cache_dir)
    p = device_cache_path(cache_dir, device_id)
    from divoom_lib.utils.atomic_io import atomic_write_text
    atomic_write_text(p, json.dumps(data, indent=2))
