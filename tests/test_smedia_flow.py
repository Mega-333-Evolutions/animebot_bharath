"""The whole /smedia flow: tapping a button, sending the media, saving it."""
import asyncio

import pytest

from plugins import smedia


class FakePhoto:
    file_id = "PHOTO_FILE_ID"


class FakeAnimation:
    file_id = "GIF_FILE_ID"


class FakeDocument:
    def __init__(self, mime_type):
        self.mime_type = mime_type
        self.file_id = "DOC_FILE_ID"


class FakeMediaMessage:
    """A message the owner sent."""

    def __init__(self, photo=None, animation=None, document=None):
        self.photo = photo
        self.animation = animation
        self.document = document
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)


class FakeSentMessage:
    """A message the bot sent."""

    def __init__(self, chat_id, text):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.text = text
        self.edits = []
        self.deleted = False

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)

    async def delete(self):
        self.deleted = True


class FakeClient:
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.sent = []
        self.cancelled = []

    async def send_message(self, chat_id, text, reply_markup=None):
        message = FakeSentMessage(chat_id, text)
        self.sent.append(message)
        return message

    async def listen(self, chat_id, media_filter, timeout=None):
        if not self.replies:
            raise asyncio.TimeoutError
        return self.replies.pop(0)

    def cancel_listener(self, chat_id):
        self.cancelled.append(chat_id)


class FakeQuery:
    def __init__(self, data, chat_id=1):
        self.data = data
        self.message = FakeSentMessage(chat_id, "menu")
        self.answers = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append(text)


@pytest.fixture
def saved_media(monkeypatch):
    """Stand in for the database, and record what the plugin saves."""
    state = {"current": None, "saved": [], "deleted": 0}

    async def get_start_media():
        return state["current"]

    async def set_start_media(media_type, file_id):
        state["current"] = {"type": media_type, "file_id": file_id}
        state["saved"].append((media_type, file_id))

    async def del_start_media():
        state["current"] = None
        state["deleted"] += 1

    monkeypatch.setattr(smedia, "get_start_media", get_start_media)
    monkeypatch.setattr(smedia, "set_start_media", set_start_media)
    monkeypatch.setattr(smedia, "del_start_media", del_start_media)
    return state


async def test_setting_the_start_image_saves_the_photo(saved_media):
    client = FakeClient([FakeMediaMessage(photo=FakePhoto())])
    query = FakeQuery("sm_image")

    await smedia.smedia_cb(client, query)

    assert saved_media["saved"] == [("photo", "PHOTO_FILE_ID")]


async def test_setting_the_start_gif_saves_the_animation(saved_media):
    client = FakeClient([FakeMediaMessage(animation=FakeAnimation())])
    query = FakeQuery("sm_gif")

    await smedia.smedia_cb(client, query)

    assert saved_media["saved"] == [("animation", "GIF_FILE_ID")]


async def test_the_owner_is_asked_for_the_media(saved_media):
    client = FakeClient([FakeMediaMessage(photo=FakePhoto())])

    await smedia.smedia_cb(client, FakeQuery("sm_image"))

    assert "photo (image)" in client.sent[0].text


async def test_sending_a_photo_when_a_gif_was_asked_for_still_saves_it(saved_media):
    client = FakeClient([FakeMediaMessage(photo=FakePhoto())])
    query = FakeQuery("sm_gif")

    await smedia.smedia_cb(client, query)

    assert saved_media["saved"] == [("photo", "PHOTO_FILE_ID")]
    assert "asked for GIF" in query.message.edits[-1]


async def test_nothing_is_saved_when_the_owner_runs_out_of_time(saved_media):
    client = FakeClient([])
    query = FakeQuery("sm_image")

    await smedia.smedia_cb(client, query)

    assert saved_media["saved"] == []
    assert "Timed out" in query.message.edits[-1]


async def test_a_file_that_is_not_an_image_is_refused_and_the_bot_keeps_waiting(saved_media):
    pdf = FakeMediaMessage(document=FakeDocument("application/pdf"))
    client = FakeClient([pdf, FakeMediaMessage(photo=FakePhoto())])
    query = FakeQuery("sm_image")

    await smedia.smedia_cb(client, query)

    assert saved_media["saved"] == [("photo", "PHOTO_FILE_ID")]
    assert "not an image or a GIF" in pdf.replies[0]


async def test_removing_the_current_media(saved_media):
    saved_media["current"] = {"type": "photo", "file_id": "PHOTO_FILE_ID"}
    query = FakeQuery("sm_del")

    await smedia.smedia_cb(FakeClient(), query)

    assert saved_media["current"] is None
    assert saved_media["deleted"] == 1


async def test_cancelling_stops_the_wait(saved_media):
    client = FakeClient()
    query = FakeQuery("sm_cancel")

    await smedia.smedia_cb(client, query)

    assert client.cancelled == [1]


async def test_closing_cancels_the_wait_and_removes_the_menu(saved_media):
    client = FakeClient()
    query = FakeQuery("sm_close")

    await smedia.smedia_cb(client, query)

    assert client.cancelled == [1]
    assert query.message.deleted is True


async def test_the_menu_shows_what_is_saved(saved_media):
    saved_media["current"] = {"type": "animation", "file_id": "GIF"}

    text, markup = await smedia.build_menu()

    assert "GIF" in text
    assert _has_button(markup, "sm_del")


async def test_the_menu_hides_the_remove_button_when_nothing_is_saved(saved_media):
    text, markup = await smedia.build_menu()

    assert "None set" in text
    assert not _has_button(markup, "sm_del")


async def test_the_menu_always_offers_image_and_gif(saved_media):
    _, markup = await smedia.build_menu()

    assert _has_button(markup, "sm_image")
    assert _has_button(markup, "sm_gif")
    assert _has_button(markup, "sm_close")


def _has_button(markup, callback_data):
    return any(
        button.callback_data == callback_data
        for row in markup.inline_keyboard
        for button in row
    )
