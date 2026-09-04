import logging
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    SUG_CONTROL_START_SAVING, SUG_CONTROL_TRANSMIT_DATA, SUG_CONTROL_TRANSMISSION_END,
    SUG_DATA_LED_EDITOR, SUG_DATA_SCROLL_ANIMATION,
    ANUD_CONTROL_START_SENDING, ANUD_CONTROL_SENDING_DATA, ANUD_CONTROL_TERMINATE_SENDING,
    ABUD_CONTROL_START_SENDING, ABUD_CONTROL_SENDING_DATA, ABUD_CONTROL_TERMINATE_SENDING,
    ABUD_CONTROL_DELETE, ABUD_CONTROL_PLAY_ARTWORK, ABUD_CONTROL_DELETE_ALL_BY_INDEX,
    AGUDI_CONTROL_WORD_SUCCESS, AGUDI_CONTROL_WORD_FAILURE
)

class AnimationUserDefine:
    """
    Handles user-defined GIF/image drawing and upload commands
    to keep Animation class strictly <= 500 lines of code.
    """
    def __init__(self, divoom: CommandSender):
        self.communicator = divoom
        self.logger = divoom.logger

    def _handle_sug_start_saving_or_terminate_sending(self, kwargs: dict) -> list | None:
        data = kwargs.get("data")
        speed = kwargs.get("speed")
        text_length = kwargs.get("text_length")
        mode = kwargs.get("mode")
        len_val = kwargs.get("len_val")

        if data is not None and len(data) >= 1:
            args = [data[0]]
            if data[0] == SUG_DATA_LED_EDITOR:  # LED editor
                if speed is not None and text_length is not None and len(data) >= 3:
                    args.append(speed)
                    args.append(text_length)
                    args.extend(data[3:])  # File data
                else:
                    self.logger.error("Missing parameters for LED editor in set_user_gif.")
                    return None
            elif data[0] == SUG_DATA_SCROLL_ANIMATION:  # Scroll animation
                if mode is not None and speed is not None and len_val is not None:
                    args.append(mode)
                    args.extend(speed.to_bytes(2, byteorder='little'))
                    args.extend(len_val.to_bytes(2, byteorder='little'))
                else:
                    self.logger.error("Missing parameters for Scroll animation in set_user_gif.")
                    return None
            return args
        self.logger.error("Missing 'data' for Start saving/Transmission end control word.")
        return None

    def _handle_sug_transmit_data(self, kwargs: dict) -> list | None:
        data = kwargs.get("data")
        if data is not None and len(data) >= 2:
            args = list(len(data).to_bytes(2, byteorder='little'))
            args.extend(data)  # Image data
            return args
        self.logger.error("Missing 'data' for Transmit data control word.")
        return None

    _sug_handlers = {
        SUG_CONTROL_START_SAVING: _handle_sug_start_saving_or_terminate_sending,
        SUG_CONTROL_TRANSMISSION_END: _handle_sug_start_saving_or_terminate_sending,
        SUG_CONTROL_TRANSMIT_DATA: _handle_sug_transmit_data,
    }

    async def set_user_gif(self, control_word: int, **kwargs) -> bool:
        """Set a user-defined picture or animation."""
        self.logger.info(f"Setting user GIF with control word {control_word} (0xb1)...")
        args = [control_word]

        handler = self._sug_handlers.get(control_word)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(f"Unknown control word for set_user_gif: {control_word}")
            return False

        return await self.communicator.send_command(COMMANDS["set user gif"], args)

    async def modify_user_gif_items(self, data: int) -> int | None:
        """Get the number of user-defined items or delete a specific item."""
        self.logger.info(f"Modifying user GIF items with data {data} (0xb6)...")
        args = [data]
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["modify user gif items"], args)
        if response and len(response) >= 1:
            return response[0]  # Item number
        return None

    def _handle_anud_start_sending(self, kwargs: dict) -> list | None:
        file_size = kwargs.get("file_size")
        index = kwargs.get("index")
        if file_size is not None and index is not None:
            return list(file_size.to_bytes(4, byteorder='little')) + list(index.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'file_size' or 'index' for Start Sending control word.")
        return None

    def _handle_anud_sending_data(self, kwargs: dict) -> list | None:
        file_size = kwargs.get("file_size")
        file_offset_id = kwargs.get("file_offset_id")
        file_data = kwargs.get("file_data")
        if file_size is not None and file_offset_id is not None and file_data is not None:
            return list(file_size.to_bytes(4, byteorder='little')) + \
                   list(file_offset_id.to_bytes(2, byteorder='little')) + \
                   file_data
        self.logger.error("Missing 'file_size', 'file_offset_id', or 'file_data' for Sending Data control word.")
        return None

    def _handle_anud_terminate_sending(self, kwargs: dict) -> list | None:
        return [] # No additional data

    _anud_handlers = {
        ANUD_CONTROL_START_SENDING: _handle_anud_start_sending,
        ANUD_CONTROL_SENDING_DATA: _handle_anud_sending_data,
        ANUD_CONTROL_TERMINATE_SENDING: _handle_anud_terminate_sending,
    }

    async def app_new_user_define(self, control_word: int, **kwargs) -> bool:
        """Send a new user-defined image frame."""
        self.logger.info(f"App new user define with control word {control_word} (0x8c)...")
        args = [control_word]

        handler = self._anud_handlers.get(control_word)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(f"Unknown control word for app_new_user_define: {control_word}")
            return False

        return await self.communicator.send_command(COMMANDS["app new user define"], args)

    def _handle_abud_start_sending(self, kwargs: dict) -> list | None:
        file_size = kwargs.get("file_size")
        index = kwargs.get("index")
        file_id = kwargs.get("file_id")
        if file_size is not None and index is not None and file_id is not None:
            return list(file_size.to_bytes(4, byteorder='little')) + \
                   list(index.to_bytes(1, byteorder='big')) + \
                   list(file_id.to_bytes(4, byteorder='big'))
        self.logger.error("Missing 'file_size' or 'index' or 'file_id' for Start Sending control word.")
        return None

    def _handle_abud_sending_data(self, kwargs: dict) -> list | None:
        file_size = kwargs.get("file_size")
        file_offset_id = kwargs.get("file_offset_id")
        file_data = kwargs.get("file_data")
        if file_size is not None and file_offset_id is not None and file_data is not None:
            return list(file_size.to_bytes(4, byteorder='little')) + \
                   list(file_offset_id.to_bytes(2, byteorder='little')) + \
                   file_data
        self.logger.error("Missing 'file_size', 'file_offset_id', or 'file_data' for Sending Data control word.")
        return None

    def _handle_abud_terminate_sending(self, kwargs: dict) -> list | None:
        return [] # No additional data

    def _handle_abud_delete_or_play_artwork(self, kwargs: dict) -> list | None:
        file_id = kwargs.get("file_id")
        index = kwargs.get("index")
        if file_id is not None and index is not None:
            return list(file_id.to_bytes(4, byteorder='big')) + \
                   list(index.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'file_id' or 'index' for Delete/Play control word.")
        return None

    def _handle_abud_delete_all_by_index(self, kwargs: dict) -> list | None:
        index = kwargs.get("index")
        if index is not None:
            return list(index.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'index' for Delete all files control word.")
        return None

    _abud_handlers = {
        ABUD_CONTROL_START_SENDING: _handle_abud_start_sending,
        ABUD_CONTROL_SENDING_DATA: _handle_abud_sending_data,
        ABUD_CONTROL_TERMINATE_SENDING: _handle_abud_terminate_sending,
        ABUD_CONTROL_DELETE: _handle_abud_delete_or_play_artwork,
        ABUD_CONTROL_PLAY_ARTWORK: _handle_abud_delete_or_play_artwork,
        ABUD_CONTROL_DELETE_ALL_BY_INDEX: _handle_abud_delete_all_by_index,
    }

    async def app_big64_user_define(self, control_word: int, **kwargs) -> bool:
        """Send a 64x64 user-defined image frame."""
        self.logger.info(f"App big64 user define with control word {control_word} (0x8d)...")
        args = [control_word]

        handler = self._abud_handlers.get(control_word)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(f"Unknown control word for app_big64_user_define: {control_word}")
            return False

        return await self.communicator.send_command(COMMANDS["app big64 user define"], args)

    async def app_get_user_define_info(self, user_index: int) -> dict | None:
        """Get information about a 64x64 user-defined image frame."""
        self.logger.info(f"App get user define info for index {user_index} (0x8e)...")
        args = user_index.to_bytes(1, byteorder='big')
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["app get user define info"], list(args))
        if response and len(response) >= 1:
            control_word = response[0]
            if control_word == AGUDI_CONTROL_WORD_SUCCESS:
                if len(response) >= 8:
                    user_index_resp = response[1]
                    total = int.from_bytes(response[2:4], byteorder='little')
                    offset = int.from_bytes(response[4:6], byteorder='little')
                    num = int.from_bytes(response[6:8], byteorder='little')
                    file_ids = []
                    for i in range(num):
                        if len(response) >= 8 + (i+1)*4:
                            file_ids.append(int.from_bytes(
                                response[8+i*4:8+(i+1)*4], byteorder='big'))
                    return {
                        "control_word": control_word,
                        "user_index": user_index_resp,
                        "total": total,
                        "offset": offset,
                        "num": num,
                        "file_ids": file_ids,
                    }
            elif control_word == AGUDI_CONTROL_WORD_FAILURE:
                if len(response) >= 2:
                    user_index_resp = response[1]
                    return {
                        "control_word": control_word,
                        "user_index": user_index_resp,
                    }
        return None
