"""DeviceSlot dataclass — replaces the ad-hoc 6-tuple in DivoomWall."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from divoom_lib.divoom import Divoom


@dataclass
class DeviceSlot:
    """A single device slot in a display wall grid.

    Attributes:
        device: The Divoom device instance for this slot.
        x: Grid column position.
        y: Grid row position.
        size: Pixel dimension of this device (16/32/64).
        width: Pixel width (for free-form layouts).
        height: Pixel height (for free-form layouts).
    """
    device: Divoom
    x: int = 0
    y: int = 0
    size: int = 16
    width: int = 0
    height: int = 0
