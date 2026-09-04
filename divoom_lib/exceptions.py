"""Domain-specific exceptions for the divoom_lib library.

These let consumers react to specific failure modes (``except
DeviceAddressMissingError``) instead of matching on message strings. Each
subclasses the built-in exception the library historically raised
(``ValueError`` / ``ConnectionError``), so existing ``except ValueError`` /
``except ConnectionError`` handlers — and tests matching on message text —
keep working.
"""


class DivoomError(Exception):
    """Base class for all divoom_lib errors."""


class DeviceAddressMissingError(DivoomError, ValueError):
    """No MAC address was provided or discovered, so a connection cannot start."""


class CharacteristicConfigError(DivoomError, ValueError):
    """Required GATT characteristic UUIDs are not fully configured."""


class DeviceConnectionError(DivoomError, ConnectionError):
    """Establishing or maintaining the BLE connection failed."""
