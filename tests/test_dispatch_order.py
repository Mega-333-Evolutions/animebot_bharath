"""Only the first matching handler of a group is run, so the order matters.

Pyrofork registers the handlers in the order the plugin files are walked and
then runs just the first one whose filter matches (pyrogram/dispatcher.py).
A command therefore only reaches its own handler if no earlier handler is
greedy enough to swallow it.
"""
import asyncio
import importlib
import os

import pytest
from pyrogram import ContinuePropagation
from pyrogram.enums import ChatType
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from config import OWNER_ID

import plugins.cbb
import plugins.channel_post
import plugins.link_generator
import plugins.smedia
import plugins.start
import plugins.useless

PLUGINS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins"
)


class FakeChat:
    type = ChatType.PRIVATE
    id = 1


class FakeUser:
    id = OWNER_ID
    username = "owner"
    usernames = None
    is_self = False
    first_name = "Owner"
    last_name = ""
    mention = "@owner"


class FakeRegularUser(FakeUser):
    """A user who is not an admin."""

    id = 12345
    username = "someone"
    mention = "@someone"


class FakeClient:
    class me:
        username = "testbot"
        usernames = None

    id = 1
    listening = {}

    def get_listener_matching_with_data(self, data, listener_type):
        return None

    async def send_message(self, chat_id, text, reply_markup=None):
        return FakeCallbackMessage()

    async def listen(self, chat_id, media_filter, timeout=None):
        raise asyncio.TimeoutError

    def cancel_listener(self, chat_id):
        pass


class FakeMessage:
    def __init__(self, text, user=None):
        self.text = text
        self.caption = None
        self.chat = FakeChat()
        self.from_user = user or FakeUser()
        self.outgoing = False
        self.command = None


def walk_order():
    """The plugin modules in the order the plugin loader walks them."""
    modules = []
    for current_root, _, filenames in os.walk(PLUGINS_DIR):
        if "__pycache__" in current_root:
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                modules.append(importlib.import_module("plugins." + filename[:-3]))
    return modules


def group_zero_handlers(modules):
    """The message handlers of group 0, in registration order."""
    handlers = []
    for module in modules:
        for attribute in vars(module).values():
            registered = getattr(attribute, "handlers", None)
            if not isinstance(registered, list):
                continue
            for handler, group in registered:
                if isinstance(handler, MessageHandler) and group == 0:
                    handlers.append(handler)
    return handlers


def callback_of(handler):
    """The function a handler runs.

    pyromod wraps every message handler in its own listener resolver, and
    keeps the original function as `user_callback`.
    """
    return getattr(handler, "user_callback", handler.callback)


async def first_matching_handler(message, handlers):
    for handler in handlers:
        if await handler.check(FakeClient(), message):
            return handler
    return None


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """The /smedia menu reads and writes the database; keep these tests off the network."""

    async def get_start_media():
        return None

    async def set_start_media(media_type, file_id):
        return None

    async def del_start_media():
        return None

    monkeypatch.setattr(plugins.smedia, "get_start_media", get_start_media)
    monkeypatch.setattr(plugins.smedia, "set_start_media", set_start_media)
    monkeypatch.setattr(plugins.smedia, "del_start_media", del_start_media)


@pytest.fixture(params=["walked", "reversed"])
def handlers(request):
    modules = walk_order()
    if request.param == "reversed":
        modules = list(reversed(modules))
    return group_zero_handlers(modules)


async def test_the_smedia_command_reaches_its_own_handler(handlers):
    handler = await first_matching_handler(FakeMessage("/smedia"), handlers)

    assert handler is not None
    assert callback_of(handler) is plugins.smedia.smedia_cmd


async def test_the_start_command_reaches_its_own_handler(handlers):
    handler = await first_matching_handler(FakeMessage("/start"), handlers)

    assert handler is not None
    assert callback_of(handler) is plugins.start.start_command


async def test_the_users_command_reaches_its_own_handler(handlers):
    handler = await first_matching_handler(FakeMessage("/users"), handlers)

    assert handler is not None
    assert callback_of(handler) is plugins.start.get_users


async def test_a_plain_message_still_gets_the_generic_reply(handlers):
    """A normal user's message is answered by the catch-all handler."""
    message = FakeMessage("hello", user=FakeRegularUser())

    handler = await first_matching_handler(message, handlers)

    assert handler is not None
    assert callback_of(handler) is plugins.useless.useless


async def test_the_owner_media_is_not_posted_to_the_db_channel(handlers):
    """While the /smedia menu is waiting, the owner's media is the start media."""
    message = FakeMessage("/smedia")

    handler = await first_matching_handler(message, handlers)

    assert callback_of(handler) is not plugins.channel_post.channel_post


class FakeCallbackChat:
    id = 1
    username = None


class FakeCallbackMessage:
    def __init__(self):
        self.chat = FakeCallbackChat()
        self.id = 5
        self.edits = []
        self.deleted = False
        self.reply_to_message = None

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)

    async def delete(self):
        self.deleted = True


class FakeCallback:
    def __init__(self, data):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeCallbackMessage()
        self.inline_message_id = None
        self.answers = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append(text)


def group_zero_callback_handlers(modules):
    """The callback query handlers of group 0, in registration order."""
    handlers = []
    for module in modules:
        for attribute in vars(module).values():
            registered = getattr(attribute, "handlers", None)
            if not isinstance(registered, list):
                continue
            for handler, group in registered:
                if isinstance(handler, CallbackQueryHandler) and group == 0:
                    handlers.append(handler)
    return handlers


async def dispatch_callback(data, handlers):
    """Run the callback handlers the way the dispatcher does.

    Only the first matching handler of a group is run, but a handler can hand
    the callback on with ContinuePropagation.
    """
    query = FakeCallback(data)
    for handler in handlers:
        if not await handler.check(FakeClient(), query):
            continue
        try:
            await handler.original_callback(FakeClient(), query)
        except ContinuePropagation:
            continue
        return handler
    return None


@pytest.fixture(params=["walked", "reversed"])
def callback_handlers(request):
    modules = walk_order()
    if request.param == "reversed":
        modules = list(reversed(modules))
    return group_zero_callback_handlers(modules)


async def test_the_smedia_buttons_reach_the_smedia_handler(callback_handlers):
    """The /smedia menu has its own buttons; they must not be swallowed."""
    for data in ("sm_image", "sm_gif", "sm_del", "sm_close"):
        handler = await dispatch_callback(data, callback_handlers)

        assert handler is not None, data
        assert handler.original_callback is plugins.smedia.smedia_cb, data


async def test_the_about_button_still_reaches_its_own_handler(callback_handlers):
    handler = await dispatch_callback("about", callback_handlers)

    assert handler is not None
    assert handler.original_callback is plugins.cbb.cb_handler
