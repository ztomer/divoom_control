# gui/photo_albums.py

from divoom_gui.cloud_panels import CloudPanelMixin


class PhotoAlbumsMixin(CloudPanelMixin):
    """Browse the photo albums ("clocks") configured for the active device,
    via the DAEMON.

    `Photo/GetAlbumList` (protocol reference: `divoom_lib/cloud.py`). R70 P2.1
    moved the call to `divoomd`. Playing an album is a separate, LAN-only
    device-touching call on LightingApi.play_album.

    This is the panel that proved the point: the daemon answers
    `Photo/GetAlbumList failed (RC=3): Request data is incomplete`, and the old
    `except -> []` here rendered that as "nothing found".
    """

    def get_photo_albums(self) -> dict:
        return self._cloud_list("photo albums", lambda c: c.get_photo_albums())
