# gui/aid_sleep.py

from divoom_gui.cloud_panels import CloudPanelMixin


class AidSleepMixin(CloudPanelMixin):
    """Browse Divoom's cloud-hosted AidSleep sound library, via the DAEMON.

    `AidSleep/GetAllList` (protocol reference: `divoom_lib/cloud.py`; confirmed
    live 2026-07-14 after fixing the RC=3 "no bound device" precondition).
    R70 P2.1 moved the call to `divoomd`. Playing a chosen sound is a separate
    device-touching call on LightingApi.play_aid_sleep — BLE/SPP JSON straight
    to the device, no cloud round-trip.
    """

    def get_aid_sleep_list(self, sleep_type: int) -> dict:
        return self._cloud_list(
            "sleep sounds", lambda c: c.get_aid_sleep_list(int(sleep_type)))
