import pytest
import os
import json
from unittest.mock import patch, mock_open
from pathlib import Path
from divoom_lib.utils import cache

# Fixture to create a temporary cache directory for tests
@pytest.fixture
def temp_cache_dir(tmp_path):
    return str(tmp_path / "test_cache")

def test_ensure_cache_dir(temp_cache_dir):
    """Test that ensure_cache_dir creates the directory if it doesn't exist."""
    assert not Path(temp_cache_dir).exists()
    cache.ensure_cache_dir(temp_cache_dir)
    assert Path(temp_cache_dir).is_dir()

def test_device_cache_path():
    """Test that device_cache_path generates the correct path and sanitizes device_id."""
    test_dir = "/tmp/test_cache"
    device_id_mac = "AA:BB:CC:DD:EE:FF"
    device_id_sanitized = "AA_BB_CC_DD_EE_FF"
    expected_path = os.path.join(test_dir, f"{device_id_sanitized}.json")
    assert cache.device_cache_path(test_dir, device_id_mac) == expected_path

def test_load_device_cache_success(temp_cache_dir):
    """Test successful loading of device cache."""
    device_id = "test_device"
    test_data = {"key": "value", "number": 123}
    
    # Manually create the cache file for the test
    cache.ensure_cache_dir(temp_cache_dir)
    file_path = cache.device_cache_path(temp_cache_dir, device_id)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(test_data, f)

    loaded_data = cache.load_device_cache(temp_cache_dir, device_id)
    assert loaded_data == test_data

def test_load_device_cache_no_file(temp_cache_dir):
    """Test loading cache when the file does not exist."""
    device_id = "non_existent_device"
    loaded_data = cache.load_device_cache(temp_cache_dir, device_id)
    assert loaded_data is None

def test_load_device_cache_invalid_json(temp_cache_dir):
    """Test loading cache when the file contains invalid JSON."""
    device_id = "invalid_json_device"
    
    cache.ensure_cache_dir(temp_cache_dir)
    file_path = cache.device_cache_path(temp_cache_dir, device_id)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("this is not json")

    loaded_data = cache.load_device_cache(temp_cache_dir, device_id)
    assert loaded_data is None

def test_save_device_cache_success(temp_cache_dir):
    """Test successful saving of device cache."""
    device_id = "new_device"
    test_data = {"new_key": "new_value"}

    cache.save_device_cache(temp_cache_dir, device_id, test_data)
    
    file_path = cache.device_cache_path(temp_cache_dir, device_id)
    assert Path(file_path).is_file()
    with open(file_path, "r", encoding="utf-8") as f:
        loaded_data = json.load(f)
    assert loaded_data == test_data

def test_save_device_cache_ensures_dir(tmp_path):
    """Test that save_device_cache creates the directory if it doesn't exist."""
    non_existent_dir = str(tmp_path / "non_existent_cache")
    device_id = "another_device"
    test_data = {"data": "here"}

    assert not Path(non_existent_dir).exists()
    cache.save_device_cache(non_existent_dir, device_id, test_data)
    assert Path(non_existent_dir).is_dir()
    file_path = cache.device_cache_path(non_existent_dir, device_id)
    assert Path(file_path).is_file()
