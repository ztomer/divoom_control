# gui/lighting_forward.py
#
# One-line JS-API forwarding methods to LightingApi, split out of gui_api.py
# to stay under the 500-line house limit. Pure delegation — no logic here;
# see divoom_gui/api/lighting.py for the actual implementations.


class LightingForwardMixin:
    def display_wall_image(self, mac: str, file_path: str, cell_size: int | None = None) -> dict:
        return self.lighting.display_wall_image(mac, file_path, cell_size)

    def push_playlist(self, mac: str, play_id: int) -> dict:
        return self.lighting.push_playlist(mac, play_id)

    def play_aid_sleep(self, mac: str, sleep_id: int, sleep_type: int = 0) -> bool:
        return self.lighting.play_aid_sleep(mac, sleep_id, sleep_type)

    def play_album(self, mac: str, album_id: int) -> dict:
        return self.lighting.play_album(mac, album_id)
