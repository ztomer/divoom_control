from divoom_lib import models
from divoom_lib.divoom import Divoom


class DivoomProtocol(Divoom):
    """Backward-compatible subclass of Divoom.

    Previously a standalone duplicate of the protocol implementation,
    now inherits from ``Divoom`` to eliminate duplication.
    All protocol framing/parsing logic lives in ``divoom_lib/framing.py``.
    """

    def __init__(self, mac: str | None = None, logger=None, **kwargs) -> None:
        super().__init__(mac=mac, logger=logger, **kwargs)
        self.type = models.DEFAULT_DEVICE_TYPE
        self.screensize = models.DEFAULT_SCREEN_SIZE
        self.chunksize = kwargs.get('chunksize', models.DEFAULT_CHUNK_SIZE)
        self.colorpalette = None
