# gui/clock_faces.py

from divoom_gui.cloud_panels import CloudPanelMixin


class ClockFacesMixin(CloudPanelMixin):
    """Browse Divoom's public clock-face catalog, via the DAEMON.

    `Channel/GetDialType` + `GetDialList` — a different, unauthenticated
    endpoint pair from the pixel-art gallery (the writeup is in
    `divoom_lib/cloud.py`, which remains the protocol reference). R70 P2.1: the
    call itself moved to `divoomd`, which has routed both commands the whole
    time. Applying a selected face still reuses set_clock() ->
    display.show_clock() on LightingApi.
    """

    def get_dial_types(self) -> dict:
        return self._cloud_list(
            "clock face categories", lambda c: c.get_dial_types())

    def get_dial_list(self, dial_type: str, page: int = 1) -> dict:
        return self._cloud_list(
            "clock faces", lambda c: c.get_dial_list(dial_type, page=page))
