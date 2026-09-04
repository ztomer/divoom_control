# gui/lighting_forward.py
#
# One-line JS-API forwarding methods to LightingApi, split out of gui_api.py
# to stay under the 500-line house limit. Pure delegation — no logic here;
# see divoom_gui/api/lighting.py for the actual implementations.


class LightingForwardMixin:
    def display_wall_image(self, file_path: str, cell_size: int) -> bool:
        return self.lighting.display_wall_image(file_path, cell_size)

    def push_playlist(self, play_id: int) -> bool:
        return self.lighting.push_playlist(play_id)

    def play_aid_sleep(self, sleep_id: int, sleep_type: int = 0) -> bool:
        return self.lighting.play_aid_sleep(sleep_id, sleep_type)

    def play_album(self, album_id: int) -> bool:
        return self.lighting.play_album(album_id)

    def set_brightness(self, brightness: int) -> bool:
        return self.lighting.set_brightness(brightness)

    def set_volume(self, volume: int) -> bool:
        return self.lighting.set_volume(volume)
