"""R53.12: SPP transport reports honest liveness (parity with BLE is_alive).

Deferred BLE finding: the pyserial `_serial_read_loop` could die on a read error
WITHOUT closing the port or setting `_close_event`, so `is_connected` kept
returning True (the port stays `.is_open`) while no data would ever arrive again.
`is_alive` now also requires the reader thread to be live on the serial path.
"""
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.bt_spp_transport import BTSppTransport


class _FakePort:
    def __init__(self, is_open=True):
        self.is_open = is_open


class _FakeThread:
    def __init__(self, alive):
        self._alive = alive
    def is_alive(self):
        return self._alive


def _t():
    return BTSppTransport("AA:BB:CC:DD:EE:FF", logger=logging.getLogger("spp_test"))


def test_is_alive_false_when_serial_reader_died():
    """The core fix: port still open (is_connected True) but reader thread dead."""
    t = _t()
    t._serial_port = _FakePort(is_open=True)
    t._serial_read_thread = _FakeThread(alive=False)
    assert t.is_connected is True      # lags True — port never got closed
    assert t.is_alive is False         # honest: the reader is dead


def test_is_alive_true_when_serial_reader_live():
    t = _t()
    t._serial_port = _FakePort(is_open=True)
    t._serial_read_thread = _FakeThread(alive=True)
    assert t.is_connected is True and t.is_alive is True


def test_is_alive_false_when_disconnected():
    t = _t()
    assert t.is_connected is False and t.is_alive is False


def test_is_alive_true_on_iobluetooth_channel_path():
    """The IOBluetooth path has no serial reader; the channel (closed via the
    rfcommChannelClosed_ delegate → _close_event) is the liveness signal."""
    t = _t()
    t._serial_port = None
    t._channel = object()
    assert t.is_connected is True and t.is_alive is True


def test_serial_read_loop_logs_and_exits_on_error(caplog):
    """The read error was swallowed silently; it must now be logged (the thread
    then dies, which is_alive reflects)."""
    t = _t()

    class _BoomPort:
        is_open = True
        def read(self, _n):
            raise OSError("device unplugged")

    t._serial_port = _BoomPort()
    with caplog.at_level(logging.WARNING):
        t._serial_read_loop()          # returns when the read raises
    assert any("serial read loop" in r.message.lower() for r in caplog.records)
