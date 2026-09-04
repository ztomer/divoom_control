# gui/playlists.py

from divoom_gui.cloud_panels import CloudPanelMixin


class PlaylistsMixin(CloudPanelMixin):
    """Browse the user's cloud-hosted playlists, via the DAEMON.

    `Playlist/GetMyList` (protocol reference: `divoom_lib/cloud.py`; confirmed
    live 2026-07-14). R70 P2.1 moved the call to `divoomd`. Pushing a playlist
    to the device is a separate device-touching call on
    LightingApi.push_playlist, forwarded from gui_api.py like every other
    device action.
    """

    def get_my_playlists(self) -> dict:
        return self._cloud_list("playlists", lambda c: c.get_my_playlists())
