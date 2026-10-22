"""Filters that decide which updates reach which handler."""
from pyrogram.enums import ChatType

from helper_func import not_command
from plugins.smedia import smedia_cb_filter


class FakeChat:
    type = ChatType.PRIVATE
    id = 1


class FakeUser:
    id = 1
    username = "owner"
    usernames = None
    is_self = False


class FakeMessage:
    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.outgoing = False
        self.command = None


class FakeCallback:
    def __init__(self, data):
        self.data = data
        self.from_user = FakeUser()


async def test_a_command_is_not_swallowed_by_the_generic_reply():
    assert await not_command(None, FakeMessage(text="/start")) is False


async def test_a_command_with_a_bot_suffix_is_not_swallowed():
    assert await not_command(None, FakeMessage(text="/start@mybot")) is False


async def test_plain_text_is_still_caught_by_the_generic_reply():
    assert await not_command(None, FakeMessage(text="hello")) is True


async def test_a_media_message_without_a_caption_is_still_caught():
    assert await not_command(None, FakeMessage(text=None, caption=None)) is True


async def test_only_sm_callbacks_reach_the_smedia_handler():
    assert await smedia_cb_filter(None, FakeCallback("sm_image")) is True
    assert await smedia_cb_filter(None, FakeCallback("sm_gif")) is True
    assert await smedia_cb_filter(None, FakeCallback("sm_del")) is True
    assert await smedia_cb_filter(None, FakeCallback("sm_close")) is True


async def test_other_callbacks_are_left_alone():
    assert await smedia_cb_filter(None, FakeCallback("start")) is False
    assert await smedia_cb_filter(None, FakeCallback("about")) is False


async def test_a_callback_without_data_is_left_alone():
    assert await smedia_cb_filter(None, FakeCallback(None)) is False
