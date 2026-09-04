"""Unit tests for divoom_lib.display.animation_user (R61 coverage push)."""

import logging

import pytest

from divoom_lib.models import (
    COMMANDS,
    SUG_CONTROL_START_SAVING, SUG_CONTROL_TRANSMIT_DATA, SUG_CONTROL_TRANSMISSION_END,
    SUG_DATA_LED_EDITOR, SUG_DATA_SCROLL_ANIMATION,
    ANUD_CONTROL_START_SENDING, ANUD_CONTROL_SENDING_DATA, ANUD_CONTROL_TERMINATE_SENDING,
    ABUD_CONTROL_START_SENDING, ABUD_CONTROL_SENDING_DATA, ABUD_CONTROL_TERMINATE_SENDING,
    ABUD_CONTROL_DELETE, ABUD_CONTROL_PLAY_ARTWORK, ABUD_CONTROL_DELETE_ALL_BY_INDEX,
    AGUDI_CONTROL_WORD_SUCCESS, AGUDI_CONTROL_WORD_FAILURE,
)
from divoom_lib.display.animation_user import AnimationUserDefine


class FakeComm:
    def __init__(self):
        self.logger = logging.getLogger("test.animation_user")
        self.calls = []
        self.send_result = True
        self.wait_response = None

    async def send_command(self, command, args=None, write_with_response=False):
        self.calls.append((command, args))
        return self.send_result

    async def send_command_and_wait_for_response(self, command, args=None, timeout=10):
        self.calls.append((command, args))
        return self.wait_response


def last_args(comm):
    return comm.calls[-1][1]


@pytest.fixture
def comm():
    return FakeComm()


@pytest.fixture
def anim(comm):
    return AnimationUserDefine(comm)


# --- set_user_gif: LED editor branch (SUG_CONTROL_START_SAVING / TRANSMISSION_END) ---

async def test_set_user_gif_led_editor_success(anim, comm):
    result = await anim.set_user_gif(
        SUG_CONTROL_START_SAVING,
        data=[SUG_DATA_LED_EDITOR, 0, 0, 9, 9],
        speed=5,
        text_length=10,
    )
    assert result is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set user gif"]
    # control_word, data[0], speed, text_length, then data[3:]
    assert args == [SUG_CONTROL_START_SAVING, SUG_DATA_LED_EDITOR, 5, 10, 9, 9]


async def test_set_user_gif_led_editor_missing_params(anim, comm):
    # len(data) < 3 -> missing branch
    result = await anim.set_user_gif(
        SUG_CONTROL_TRANSMISSION_END,
        data=[SUG_DATA_LED_EDITOR],
        speed=5,
        text_length=10,
    )
    assert result is False
    assert comm.calls == []


async def test_set_user_gif_led_editor_missing_speed(anim, comm):
    result = await anim.set_user_gif(
        SUG_CONTROL_START_SAVING,
        data=[SUG_DATA_LED_EDITOR, 0, 0, 9],
        text_length=10,
    )
    assert result is False


# --- set_user_gif: scroll animation branch ---

async def test_set_user_gif_scroll_animation_success(anim, comm):
    result = await anim.set_user_gif(
        SUG_CONTROL_START_SAVING,
        data=[SUG_DATA_SCROLL_ANIMATION],
        mode=1,
        speed=300,
        len_val=20,
    )
    assert result is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set user gif"]
    assert args == [SUG_CONTROL_START_SAVING, SUG_DATA_SCROLL_ANIMATION, 1, 300 & 0xFF, 300 >> 8, 20, 0]


async def test_set_user_gif_scroll_animation_missing_params(anim, comm):
    result = await anim.set_user_gif(
        SUG_CONTROL_TRANSMISSION_END,
        data=[SUG_DATA_SCROLL_ANIMATION],
        mode=1,
    )
    assert result is False
    assert comm.calls == []


async def test_set_user_gif_unknown_data_passthrough(anim, comm):
    # data[0] neither LED editor nor scroll animation -> just passthrough of data[0]
    result = await anim.set_user_gif(SUG_CONTROL_START_SAVING, data=[99])
    assert result is True
    cmd, args = comm.calls[-1]
    assert args == [SUG_CONTROL_START_SAVING, 99]


async def test_set_user_gif_missing_data(anim, comm):
    result = await anim.set_user_gif(SUG_CONTROL_START_SAVING)
    assert result is False
    assert comm.calls == []


async def test_set_user_gif_missing_data_empty_list(anim, comm):
    result = await anim.set_user_gif(SUG_CONTROL_START_SAVING, data=[])
    assert result is False


# --- set_user_gif: transmit data branch ---

async def test_set_user_gif_transmit_data_success(anim, comm):
    result = await anim.set_user_gif(SUG_CONTROL_TRANSMIT_DATA, data=[1, 2, 3])
    assert result is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set user gif"]
    assert args == [SUG_CONTROL_TRANSMIT_DATA, 3, 0, 1, 2, 3]


async def test_set_user_gif_transmit_data_missing(anim, comm):
    result = await anim.set_user_gif(SUG_CONTROL_TRANSMIT_DATA, data=[1])
    assert result is False
    assert comm.calls == []


async def test_set_user_gif_transmit_data_no_data(anim, comm):
    result = await anim.set_user_gif(SUG_CONTROL_TRANSMIT_DATA)
    assert result is False


# --- set_user_gif: unknown control word ---

async def test_set_user_gif_unknown_control_word(anim, comm):
    result = await anim.set_user_gif(0xFF)
    assert result is False
    assert comm.calls == []


# --- modify_user_gif_items ---

async def test_modify_user_gif_items_success(anim, comm):
    comm.wait_response = [7]
    result = await anim.modify_user_gif_items(1)
    assert result == 7
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["modify user gif items"]
    assert args == [1]


async def test_modify_user_gif_items_empty_response(anim, comm):
    comm.wait_response = []
    result = await anim.modify_user_gif_items(1)
    assert result is None


async def test_modify_user_gif_items_none_response(anim, comm):
    comm.wait_response = None
    result = await anim.modify_user_gif_items(1)
    assert result is None


# --- app_new_user_define ---

async def test_app_new_user_define_start_sending_success(anim, comm):
    result = await anim.app_new_user_define(
        ANUD_CONTROL_START_SENDING, file_size=1024, index=2,
    )
    assert result is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["app new user define"]
    assert args[0] == ANUD_CONTROL_START_SENDING
    assert args[1:5] == list((1024).to_bytes(4, byteorder="little"))
    assert args[5:6] == list((2).to_bytes(1, byteorder="big"))


async def test_app_new_user_define_start_sending_missing(anim, comm):
    result = await anim.app_new_user_define(ANUD_CONTROL_START_SENDING, file_size=1024)
    assert result is False
    assert comm.calls == []


async def test_app_new_user_define_sending_data_success(anim, comm):
    result = await anim.app_new_user_define(
        ANUD_CONTROL_SENDING_DATA, file_size=10, file_offset_id=1, file_data=[9, 9],
    )
    assert result is True
    args = last_args(comm)
    assert args[0] == ANUD_CONTROL_SENDING_DATA
    assert args[-2:] == [9, 9]


async def test_app_new_user_define_sending_data_missing(anim, comm):
    result = await anim.app_new_user_define(ANUD_CONTROL_SENDING_DATA, file_size=10)
    assert result is False


async def test_app_new_user_define_terminate_sending(anim, comm):
    result = await anim.app_new_user_define(ANUD_CONTROL_TERMINATE_SENDING)
    assert result is True
    args = last_args(comm)
    assert args == [ANUD_CONTROL_TERMINATE_SENDING]


async def test_app_new_user_define_unknown_control_word(anim, comm):
    result = await anim.app_new_user_define(0xFF)
    assert result is False
    assert comm.calls == []


# --- app_big64_user_define ---

async def test_app_big64_start_sending_success(anim, comm):
    result = await anim.app_big64_user_define(
        ABUD_CONTROL_START_SENDING, file_size=2048, index=1, file_id=555,
    )
    assert result is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["app big64 user define"]
    assert args[0] == ABUD_CONTROL_START_SENDING


async def test_app_big64_start_sending_missing(anim, comm):
    result = await anim.app_big64_user_define(ABUD_CONTROL_START_SENDING, file_size=2048)
    assert result is False
    assert comm.calls == []


async def test_app_big64_sending_data_success(anim, comm):
    result = await anim.app_big64_user_define(
        ABUD_CONTROL_SENDING_DATA, file_size=10, file_offset_id=1, file_data=[1, 2],
    )
    assert result is True
    args = last_args(comm)
    assert args[-2:] == [1, 2]


async def test_app_big64_sending_data_missing(anim, comm):
    result = await anim.app_big64_user_define(ABUD_CONTROL_SENDING_DATA, file_size=10)
    assert result is False


async def test_app_big64_terminate_sending(anim, comm):
    result = await anim.app_big64_user_define(ABUD_CONTROL_TERMINATE_SENDING)
    assert result is True
    args = last_args(comm)
    assert args == [ABUD_CONTROL_TERMINATE_SENDING]


async def test_app_big64_delete_success(anim, comm):
    result = await anim.app_big64_user_define(
        ABUD_CONTROL_DELETE, file_id=123, index=4,
    )
    assert result is True
    args = last_args(comm)
    assert args[0] == ABUD_CONTROL_DELETE


async def test_app_big64_play_artwork_success(anim, comm):
    result = await anim.app_big64_user_define(
        ABUD_CONTROL_PLAY_ARTWORK, file_id=123, index=4,
    )
    assert result is True
    args = last_args(comm)
    assert args[0] == ABUD_CONTROL_PLAY_ARTWORK


async def test_app_big64_delete_or_play_missing(anim, comm):
    result = await anim.app_big64_user_define(ABUD_CONTROL_DELETE, file_id=123)
    assert result is False
    assert comm.calls == []


async def test_app_big64_delete_all_by_index_success(anim, comm):
    result = await anim.app_big64_user_define(
        ABUD_CONTROL_DELETE_ALL_BY_INDEX, index=3,
    )
    assert result is True
    args = last_args(comm)
    assert args == [ABUD_CONTROL_DELETE_ALL_BY_INDEX, 3]


async def test_app_big64_delete_all_by_index_missing(anim, comm):
    result = await anim.app_big64_user_define(ABUD_CONTROL_DELETE_ALL_BY_INDEX)
    assert result is False
    assert comm.calls == []


async def test_app_big64_unknown_control_word(anim, comm):
    result = await anim.app_big64_user_define(0xFF)
    assert result is False
    assert comm.calls == []


# --- app_get_user_define_info ---

async def test_app_get_user_define_info_none_response(anim, comm):
    comm.wait_response = None
    result = await anim.app_get_user_define_info(1)
    assert result is None


async def test_app_get_user_define_info_empty_response(anim, comm):
    comm.wait_response = []
    result = await anim.app_get_user_define_info(1)
    assert result is None


async def test_app_get_user_define_info_success_with_file_ids(anim, comm):
    # control_word=SUCCESS, user_index=2, total=1, offset=0, num=2, then 2 file_ids
    payload = [AGUDI_CONTROL_WORD_SUCCESS, 2]
    payload += list((1).to_bytes(2, byteorder="little"))  # total
    payload += list((0).to_bytes(2, byteorder="little"))  # offset
    payload += list((2).to_bytes(2, byteorder="little"))  # num
    payload += list((111).to_bytes(4, byteorder="big"))
    payload += list((222).to_bytes(4, byteorder="big"))
    comm.wait_response = payload

    result = await anim.app_get_user_define_info(2)
    assert result == {
        "control_word": AGUDI_CONTROL_WORD_SUCCESS,
        "user_index": 2,
        "total": 1,
        "offset": 0,
        "num": 2,
        "file_ids": [111, 222],
    }


async def test_app_get_user_define_info_success_truncated_file_ids(anim, comm):
    # num=2 but response too short for the second file_id -> only first collected
    payload = [AGUDI_CONTROL_WORD_SUCCESS, 2]
    payload += list((1).to_bytes(2, byteorder="little"))
    payload += list((0).to_bytes(2, byteorder="little"))
    payload += list((2).to_bytes(2, byteorder="little"))  # num=2
    payload += list((111).to_bytes(4, byteorder="big"))  # only 1 file_id present
    comm.wait_response = payload

    result = await anim.app_get_user_define_info(2)
    assert result["num"] == 2
    assert result["file_ids"] == [111]


async def test_app_get_user_define_info_success_too_short_header(anim, comm):
    # control_word=SUCCESS but len(response) < 8 -> falls through to None
    comm.wait_response = [AGUDI_CONTROL_WORD_SUCCESS, 1, 0, 0]
    result = await anim.app_get_user_define_info(1)
    assert result is None


async def test_app_get_user_define_info_failure(anim, comm):
    comm.wait_response = [AGUDI_CONTROL_WORD_FAILURE, 5]
    result = await anim.app_get_user_define_info(5)
    assert result == {
        "control_word": AGUDI_CONTROL_WORD_FAILURE,
        "user_index": 5,
    }


async def test_app_get_user_define_info_failure_too_short(anim, comm):
    comm.wait_response = [AGUDI_CONTROL_WORD_FAILURE]
    result = await anim.app_get_user_define_info(5)
    assert result is None


async def test_app_get_user_define_info_unknown_control_word(anim, comm):
    comm.wait_response = [0xFF, 1]
    result = await anim.app_get_user_define_info(1)
    assert result is None
