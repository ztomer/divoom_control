"""
lan_transport_photo.py — Photo album management, split out of
lan_transport.py to stay under the 500-line house limit.

All in HttpCommand.DeviceAndServerCmd (LAN-routed on WiFi) except
get_photo_list, which is in ForceDeviceHttp (always local, never cloud).
Browse albums via divoom_lib.cloud.CloudClient.get_photo_albums
(Photo/GetAlbumList — a plain cloud call, not device-scoped) to find an
AlbumId/ClockId. See docs/cloud_api/photo_discover.md.
"""

from divoom_lib.transport import Transport, via


class LanPhotoMixin:
    """Photo album methods mixed into LanTransport — relies on the host
    class's ``self.post()``."""

    @via(Transport.LAN)
    async def play_album(self, album_id: int) -> dict:
        """
        Start slideshow playback of a photo album on the device screen.

        Transport:  LAN

        Args:
            album_id: The album's ``AlbumId``/``ClockId`` (from
                ``CloudClient.get_photo_albums``).

        Usage::

            await lan.play_album(7)
        """
        return await self.post("Photo/PlayAlbum", {"AlbumId": album_id})

    @via(Transport.LAN)
    async def set_album_cover(self, clock_id: int, file_id: str, photo_id: int) -> dict:
        """
        Set the cover thumbnail image for an album.

        Transport:  LAN

        Usage::

            await lan.set_album_cover(clock_id=7, file_id="abc123", photo_id=1)
        """
        return await self.post("Photo/SetAlbumCover", {
            "ClockId": clock_id, "FileId": file_id, "PhotoId": photo_id,
        })

    @via(Transport.LAN)
    async def delete_photo(self, clock_id: int, photo_list: list[int]) -> dict:
        """
        Delete one or more photos from an album.

        Transport:  LAN

        Usage::

            await lan.delete_photo(clock_id=7, photo_list=[1, 2])
        """
        return await self.post("Photo/DeletePhoto", {
            "ClockId": clock_id, "PhotoList": photo_list,
        })

    @via(Transport.LAN)
    async def remove_photo_from_album(self, clock_id: int, photo_list: list[int]) -> dict:
        """
        Remove specific photos from an album (keeps them on-device, unlike
        ``delete_photo``).

        Transport:  LAN

        Usage::

            await lan.remove_photo_from_album(clock_id=7, photo_list=[1, 2])
        """
        return await self.post("Photo/RemovePhotoFromAlbum", {
            "ClockId": clock_id, "PhotoList": photo_list,
        })

    @via(Transport.LAN)
    async def move_photo_to_album(self, to_clock_id: int, photo_list: list[int]) -> dict:
        """
        Move photos already stored on the device into a target album.

        Transport:  LAN

        Usage::

            await lan.move_photo_to_album(to_clock_id=8, photo_list=[1, 2])
        """
        return await self.post("Photo/DevicePhotoToAlbum", {
            "ToClockId": to_clock_id, "PhotoList": photo_list,
        })

    @via(Transport.LAN)
    async def get_photo_list(
        self, clock_id: int, *, parent_clock_id: int = 0, parent_item_id: int = 0,
        limit: int = 30, page: int = 1,
    ) -> dict:
        """
        Paginated listing of photos within a given album.

        Transport:  LAN — always local (``HttpCommand.ForceDeviceHttp``),
        never reaches the cloud even when the app would otherwise prefer it.

        Usage::

            await lan.get_photo_list(clock_id=7)
        """
        start = (page - 1) * limit + 1
        end = page * limit
        return await self.post("Photo/GetPhotoList", {
            "ClockId": clock_id, "ParentClockId": parent_clock_id,
            "ParentItemId": parent_item_id, "StartNum": start, "EndNum": end,
        })
