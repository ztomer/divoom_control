#!/usr/bin/env python3
"""
devices_db.py — Divoom device model database.
Stores hardware specifications, screen sizes, resolutions, and feature flags
for different Divoom hardware models.
"""

from typing import Dict, Any, Optional

DEVICES_DATABASE = {
    "timoo": {
        "model_name": "Divoom Timoo",
        "resolution": 16,
        "width": 16,
        "height": 16,
        "screen_size_inch": 4.3,
        "has_speaker": True,
        "has_battery": True,
        "ble_prefixes": ["timoo"],
        "mockup_asset": "timoo.png"
    },
    "ditoo": {
        "model_name": "Divoom Ditoo Pro / Ditoo Plus",
        "resolution": 16,
        "width": 16,
        "height": 16,
        "screen_size_inch": 3.5,
        "has_speaker": True,
        "has_battery": True,
        "ble_prefixes": ["ditoo", "ditto"],
        "mockup_asset": "ditoo.png"
    },
    "pixoo": {
        "model_name": "Divoom Pixoo Max / Pixoo",
        "resolution": 16,
        "width": 16,
        "height": 16,
        "screen_size_inch": 8.6,
        "has_speaker": False,
        "has_battery": True,
        "ble_prefixes": ["pixoo", "pixoo-light"],
        "mockup_asset": "pixoo.png"
    },
    "timebox": {
        "model_name": "Divoom Timebox Evo",
        "resolution": 16,
        "width": 16,
        "height": 16,
        "screen_size_inch": 3.9,
        "has_speaker": True,
        "has_battery": True,
        "ble_prefixes": ["timebox", "evo"],
        "mockup_asset": "timebox.png"
    },
    "tivoo": {
        "model_name": "Divoom Tivoo Max / Tivoo",
        "resolution": 16,
        "width": 16,
        "height": 16,
        "screen_size_inch": 2.5,
        "has_speaker": True,
        "has_battery": True,
        "ble_prefixes": ["tivoo"],
        "mockup_asset": "tivoo.png"
    },
    "pixoo64": {
        "model_name": "Divoom Pixoo 64",
        "resolution": 64,
        "width": 64,
        "height": 64,
        "screen_size_inch": 10.3,
        "has_speaker": False,
        "has_battery": False,
        "ble_prefixes": ["pixoo64", "pixoo-64"],
        "mockup_asset": "pixoo64.png"
    },
    "timegate": {
        "model_name": "Divoom TimeGate",
        "resolution": 128,
        "width": 128,
        "height": 32,
        "screen_size_inch": 10.5,
        "has_speaker": False,
        "has_battery": False,
        "ble_prefixes": ["timegate"],
        "mockup_asset": "timegate.png"
    }
}

def lookup_device_by_name(ble_name: str) -> Optional[Dict[str, Any]]:
    """
    Looks up a device in the database by its BLE name.
    Matches using prefix substrings (case-insensitive).
    """
    if not ble_name:
        return None
        
    name_lower = ble_name.lower()
    for key, spec in DEVICES_DATABASE.items():
        for prefix in spec["ble_prefixes"]:
            if prefix in name_lower:
                return spec
                
    # Return a default 16x16 device if no matches found
    return {
        "model_name": ble_name,
        "resolution": 16,
        "width": 16,
        "height": 16,
        "screen_size_inch": 4.0,
        "has_speaker": False,
        "has_battery": True,
        "ble_prefixes": [],
        "mockup_asset": "pixoo.png"
    }
