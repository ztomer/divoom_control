import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError
from divoom_lib.utils import discovery

# Suppress logging output during tests for cleaner output
@pytest.fixture(autouse=True)
def no_logging(caplog):
    caplog.set_level(logging.CRITICAL)

@pytest.fixture
def mock_bleak_device():
    """Mock a Bleak device object."""
    device = MagicMock()
    device.name = "Divoom Mock"
    device.address = "AA:BB:CC:DD:EE:FF"
    return device

@pytest.fixture
def mock_bleak_scanner_discover():
    """Mock BleakScanner.discover."""
    with patch('divoom_lib.utils.discovery.BleakScanner.discover', new_callable=AsyncMock) as mock_discover:
        yield mock_discover

@pytest.fixture
def mock_bleak_client():
    """Mock a BleakClient instance."""
    client = AsyncMock(spec=BleakClient)
    client.services = [] # Initialize with empty services
    return client

# discover_device now early-exits on first match via a detection callback (R53.16),
# so these use the callback-based `fake_scanner` fixture (defined below).

@pytest.mark.asyncio
async def test_discover_device_by_name_success(fake_scanner, mock_bleak_device):
    """discover_device by name substring — returns on the first matching advert."""
    fake_scanner.devices = [mock_bleak_device]
    device, device_id = await discovery.discover_device(name_substring="Divoom Mock")
    assert device is mock_bleak_device
    assert device_id == mock_bleak_device.address
    assert fake_scanner.instances[0].stopped is True       # scanner always stopped

@pytest.mark.asyncio
async def test_discover_device_by_name_not_found(fake_scanner, monkeypatch):
    """No match → None at the (here tiny) name-scan window."""
    monkeypatch.setattr(discovery, "NAME_SCAN_TIMEOUT", 0.05)
    fake_scanner.devices = []
    device, device_id = await discovery.discover_device(name_substring="NonExistent")
    assert device is None and device_id is None

@pytest.mark.asyncio
async def test_discover_device_by_address_resolved(fake_scanner, mock_bleak_device):
    """discover_device by address — early-exits on the first address match."""
    fake_scanner.devices = [mock_bleak_device]
    device, device_id = await discovery.discover_device(address="AA:BB:CC:DD:EE:FF")
    assert device is mock_bleak_device
    assert device_id == mock_bleak_device.address

@pytest.mark.asyncio
async def test_discover_device_by_address_not_resolved(fake_scanner, monkeypatch):
    """Unresolved address falls back to the raw address string."""
    monkeypatch.setattr(discovery, "ADDR_SCAN_TIMEOUT", 0.05)
    fake_scanner.devices = []
    device, device_id = await discovery.discover_device(address="AA:BB:CC:DD:EE:FF")
    assert device == "AA:BB:CC:DD:EE:FF"                    # raw address string
    assert device_id == "AA:BB:CC:DD:EE:FF"

@pytest.mark.asyncio
async def test_discover_characteristics_success(mock_bleak_client):
    """Test discover_characteristics successfully finds characteristics."""
    # Mock services and characteristics
    mock_char_write = MagicMock(uuid="write_uuid", properties=["write"])
    mock_char_notify = MagicMock(uuid="notify_uuid", properties=["notify"])
    mock_char_read = MagicMock(uuid="read_uuid", properties=["read"])
    mock_char_write_notify = MagicMock(uuid="write_notify_uuid", properties=["write", "notify"])

    mock_service = MagicMock()
    mock_service.characteristics = [mock_char_write, mock_char_notify, mock_char_read, mock_char_write_notify]
    mock_bleak_client.services = [mock_service]

    write_chars, notify_chars, read_chars = await discovery.discover_characteristics(mock_bleak_client)

    assert len(write_chars) == 2 # write_uuid, write_notify_uuid
    assert mock_char_write in write_chars
    assert mock_char_write_notify in write_chars

    assert len(notify_chars) == 2 # notify_uuid, write_notify_uuid
    assert mock_char_notify in notify_chars
    assert mock_char_write_notify in notify_chars

    assert len(read_chars) == 1 # read_uuid
    assert mock_char_read in read_chars

@pytest.mark.asyncio
async def test_discover_characteristics_no_services(mock_bleak_client):
    """Test discover_characteristics when no services are found."""
    mock_bleak_client.services = [] # No services
    
    write_chars, notify_chars, read_chars = await discovery.discover_characteristics(mock_bleak_client)
    assert write_chars == []
    assert notify_chars == []
    assert read_chars == []

@pytest.mark.asyncio
async def test_discover_characteristics_bleak_error(mock_bleak_client):
    """Test discover_characteristics handles BleakError during service access."""
    # Simulate BleakError when accessing client.services
    error_client = mock_bleak_client
    error_client.services = []
    # Patch getattr to raise BleakError on the first few calls
    original_getattr = getattr
    call_count = [0]
    def patched_getattr(obj, name, default=None):
        if name == "services" and call_count[0] < 6:
            call_count[0] += 1
            raise BleakError("Service error")
        return original_getattr(obj, name, default)
    import builtins
    with patch.object(builtins, 'getattr', patched_getattr):
        write_chars, notify_chars, read_chars = await discovery.discover_characteristics(error_client)
    assert write_chars == []
    assert notify_chars == []
    assert read_chars == []

def test_pick_char_uuid_preferred_uuid_exact_match():
    """Test pick_char_uuid with exact preferred_uuid match."""
    mock_char1 = MagicMock(uuid="1234-5678-90ab", properties=["write"])
    mock_char2 = MagicMock(uuid="abcd-efgh-ijkl", properties=["notify"])
    candidates = [mock_char1, mock_char2]
    assert discovery.pick_char_uuid("1234-5678-90ab", candidates) == "1234-5678-90ab"

def test_pick_char_uuid_preferred_uuid_no_match():
    """Test pick_char_uuid with preferred_uuid but no exact match."""
    mock_char1 = MagicMock(uuid="1234-5678-90ab", properties=["write"])
    candidates = [mock_char1]
    assert discovery.pick_char_uuid("non-existent-uuid", candidates) == "1234-5678-90ab" # Falls back to other logic

def test_pick_char_uuid_write_notify_with_hint():
    """Test pick_char_uuid prioritizes write+notify with hint."""
    mock_char1 = MagicMock(uuid="49535343-1111-2222", properties=["write"])
    mock_char2 = MagicMock(uuid="49535343-3333-4444", properties=["write", "notify"])
    mock_char3 = MagicMock(uuid="abcd-efgh-ijkl", properties=["write", "notify"])
    candidates = [mock_char1, mock_char2, mock_char3]
    assert discovery.pick_char_uuid(None, candidates, prefix_hint="49535343") == "49535343-3333-4444"

def test_pick_char_uuid_write_notify_no_hint():
    """Test pick_char_uuid prioritizes write+notify without hint."""
    mock_char1 = MagicMock(uuid="1234-5678-90ab", properties=["write"])
    mock_char2 = MagicMock(uuid="abcd-efgh-ijkl", properties=["write", "notify"])
    candidates = [mock_char1, mock_char2]
    assert discovery.pick_char_uuid(None, candidates, prefix_hint="non-matching") == "abcd-efgh-ijkl"

def test_pick_char_uuid_fallback_hint_match():
    """Test pick_char_uuid falls back to hint match."""
    mock_char1 = MagicMock(uuid="1234-5678-90ab", properties=["write"])
    mock_char2 = MagicMock(uuid="49535343-3333-4444", properties=["read"])
    candidates = [mock_char1, mock_char2]
    assert discovery.pick_char_uuid(None, candidates, prefix_hint="49535343") == "49535343-3333-4444"

def test_pick_char_uuid_fallback_first_candidate():
    """Test pick_char_uuid falls back to first candidate."""
    mock_char1 = MagicMock(uuid="1234-5678-90ab", properties=["read"])
    mock_char2 = MagicMock(uuid="abcd-efgh-ijkl", properties=["notify"])
    candidates = [mock_char1, mock_char2]
    assert discovery.pick_char_uuid(None, candidates, prefix_hint="non-matching") == "1234-5678-90ab"

def test_pick_char_uuid_empty_candidates():
    """Test pick_char_uuid with empty candidates list."""
    assert discovery.pick_char_uuid(None, []) is None
    assert discovery.pick_char_uuid("any-uuid", []) is None


# ── is_divoom_name / discover_all_divoom_devices (R28 scan filter) ──────────

def test_is_divoom_name_matches_known_products():
    assert discovery.is_divoom_name("Ditoo-light-2")
    assert discovery.is_divoom_name("Pixoo64")
    assert discovery.is_divoom_name("Divoom Backpack")
    assert discovery.is_divoom_name("TIMEBOX-Evo")  # case-insensitive


def test_is_divoom_name_rejects_non_divoom():
    assert not discovery.is_divoom_name("AirPods Pro")
    assert not discovery.is_divoom_name("Galaxy Watch")
    assert not discovery.is_divoom_name("")
    assert not discovery.is_divoom_name(None)


def _dev(name, address):
    d = MagicMock()
    d.name = name
    d.address = address
    return d


class _FakeScanner:
    """A BleakScanner stand-in: fires the detection callback for a fixed device
    list on start(), records that stop() was called. Lets us test the callback +
    early-exit path without a real BLE adapter."""
    instances = []

    def __init__(self, detection_callback=None):
        self._cb = detection_callback
        self.started = False
        self.stopped = False
        _FakeScanner.instances.append(self)

    async def start(self):
        self.started = True
        for d in self.devices:                 # class attr set by the fixture
            self._cb(d, None)

    async def stop(self):
        self.stopped = True


@pytest.fixture
def fake_scanner():
    """Patch BleakScanner with _FakeScanner; set `.devices` on the returned class
    to control what the callback sees."""
    _FakeScanner.instances = []
    _FakeScanner.devices = []
    with patch("divoom_lib.utils.discovery.BleakScanner", _FakeScanner):
        yield _FakeScanner


@pytest.mark.asyncio
async def test_discover_all_filters_non_divoom(fake_scanner):
    """Only Divoom-named peripherals are returned — never the whole BLE list."""
    fake_scanner.devices = [
        _dev("Ditoo-light-2", "AA:11"),
        _dev("AirPods Pro", "BB:22"),
        _dev("Pixoo64", "CC:33"),
        _dev(None, "DD:44"),  # unnamed
    ]
    results = await discovery.discover_all_divoom_devices(timeout=0.05)
    addrs = {r["address"] for r in results}
    assert addrs == {"AA:11", "CC:33"}
    assert fake_scanner.instances[0].stopped is True   # scanner always stopped


@pytest.mark.asyncio
async def test_discover_all_no_fallback_to_all_devices(fake_scanner):
    """When nothing matches, return an empty list — NOT every named device."""
    fake_scanner.devices = [
        _dev("AirPods Pro", "BB:22"),
        _dev("Galaxy Watch", "EE:55"),
    ]
    results = await discovery.discover_all_divoom_devices(timeout=0.05)
    assert results == []


@pytest.mark.asyncio
async def test_discover_all_dedupes_repeated_adverts(fake_scanner):
    """A device that advertises several times is counted once."""
    fake_scanner.devices = [
        _dev("Pixoo-1", "AA:11"),
        _dev("Pixoo-1", "AA:11"),   # repeat advert
        _dev("Ditoo-2", "BB:22"),
    ]
    results = await discovery.discover_all_divoom_devices(timeout=0.05)
    assert {r["address"] for r in results} == {"AA:11", "BB:22"}


@pytest.mark.asyncio
async def test_discover_all_early_exit_returns_before_timeout(fake_scanner):
    """With `expected` set, the scan returns as soon as that many devices are
    seen — it must NOT wait out the (long) timeout. A 30s timeout with all
    devices delivered on start() must complete near-instantly."""
    fake_scanner.devices = [
        _dev("Pixoo-1", "AA:11"),
        _dev("Ditoo-2", "BB:22"),
        _dev("Timoo-3", "CC:33"),
        _dev("Tivoo-4", "DD:44"),
    ]
    completed = await asyncio.wait_for(
        discovery.discover_all_divoom_devices(timeout=30.0, expected=4),
        timeout=5.0,     # would raise if it actually waited the 30s window
    )
    assert len(completed) == 4
    assert fake_scanner.instances[0].stopped is True


def test_check_bluetooth_permission_denied():
    """When macOS Bluetooth authorization is denied (status 2), return False cleanly."""
    mock_cb = MagicMock()
    mock_cb.CBCentralManager.authorization.return_value = 2
    with patch.dict("sys.modules", {"CoreBluetooth": mock_cb}), patch("sys.platform", "darwin"):
        ok, reason = discovery.check_bluetooth_permission()
        assert ok is False
        assert "denied or restricted" in reason


def test_check_bluetooth_permission_allowed():
    """When macOS Bluetooth authorization is allowed (status 3), return True."""
    mock_cb = MagicMock()
    mock_cb.CBCentralManager.authorization.return_value = 3
    with patch.dict("sys.modules", {"CoreBluetooth": mock_cb}), patch("sys.platform", "darwin"):
        ok, reason = discovery.check_bluetooth_permission()
        assert ok is True
        assert reason == "ok"

