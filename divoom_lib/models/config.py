# divoom_lib/models/config.py

class DivoomConfig:
    def __init__(
        self,
        mac: str | None = None,
        logger: object | None = None,
        write_characteristic_uuid: str = "49535343-8841-43f4-a8d4-ecbe34729bb3",
        notify_characteristic_uuid: str = "49535343-1e4d-4bd9-ba61-23c647249616",
        read_characteristic_uuid: str = "49535343-1e4d-4bd9-ba61-23c647249616",
        spp_characteristic_uuid: str | None = None,
        escapePayload: bool = False,
        use_ios_le_protocol: bool | None = None,
        device_name: str | None = None,
        client: object | None = None,
        screensize: int | None = None,
        device_type: str | None = None,
    ):
        self.mac = mac
        self.logger = logger
        self.write_characteristic_uuid = write_characteristic_uuid
        self.notify_characteristic_uuid = notify_characteristic_uuid
        self.read_characteristic_uuid = read_characteristic_uuid
        self.spp_characteristic_uuid = spp_characteristic_uuid
        self.escapePayload = escapePayload
        self.use_ios_le_protocol = use_ios_le_protocol
        self.device_name = device_name
        self.client = client
        self.screensize = screensize
        self.device_type = device_type
