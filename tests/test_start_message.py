"""`/start` shows the saved start media, or plain text when there is none."""
from helper_func import send_start_message


class FakeMessage:
    def __init__(self, fail_photo=False, fail_animation=False):
        self.calls = []
        self.fail_photo = fail_photo
        self.fail_animation = fail_animation

    async def reply_photo(self, **kwargs):
        if self.fail_photo:
            raise RuntimeError("PHOTO_INVALID_FILE_ID")
        self.calls.append(("photo", kwargs))

    async def reply_animation(self, **kwargs):
        if self.fail_animation:
            raise RuntimeError("ANIMATION_INVALID_FILE_ID")
        self.calls.append(("animation", kwargs))

    async def reply_text(self, **kwargs):
        self.calls.append(("text", kwargs))


def saved(monkeypatch, media):
    monkeypatch.setattr("helper_func.get_start_media", _stub(media))


def _stub(media):
    async def get_start_media():
        return media

    return get_start_media


async def test_a_saved_photo_is_sent_as_a_photo(monkeypatch):
    saved(monkeypatch, {"type": "photo", "file_id": "PHOTO_ID"})
    message = FakeMessage()

    await send_start_message(message, "hello", None)

    kind, kwargs = message.calls[0]
    assert kind == "photo"
    assert kwargs["photo"] == "PHOTO_ID"
    assert kwargs["caption"] == "hello"


async def test_a_saved_gif_is_sent_as_an_animation(monkeypatch):
    saved(monkeypatch, {"type": "animation", "file_id": "GIF_ID"})
    message = FakeMessage()

    await send_start_message(message, "hello", None)

    kind, kwargs = message.calls[0]
    assert kind == "animation"
    assert kwargs["animation"] == "GIF_ID"
    assert kwargs["caption"] == "hello"


async def test_without_saved_media_the_start_message_is_plain_text(monkeypatch):
    saved(monkeypatch, None)
    message = FakeMessage()

    await send_start_message(message, "hello", None)

    kind, kwargs = message.calls[0]
    assert kind == "text"
    assert kwargs["text"] == "hello"


async def test_an_unknown_media_type_falls_back_to_plain_text(monkeypatch):
    saved(monkeypatch, {"type": "sticker", "file_id": "STICKER_ID"})
    message = FakeMessage()

    await send_start_message(message, "hello", None)

    assert message.calls[0][0] == "text"


async def test_saved_media_without_a_file_id_falls_back_to_plain_text(monkeypatch):
    saved(monkeypatch, {"type": "photo", "file_id": ""})
    message = FakeMessage()

    await send_start_message(message, "hello", None)

    assert message.calls[0][0] == "text"


async def test_the_buttons_are_passed_along(monkeypatch):
    saved(monkeypatch, {"type": "photo", "file_id": "PHOTO_ID"})
    message = FakeMessage()
    buttons = object()

    await send_start_message(message, "hello", buttons)

    assert message.calls[0][1]["reply_markup"] is buttons


async def test_a_broken_image_id_falls_back_to_plain_text(monkeypatch):
    """A file_id can go stale (the bot token changed); /start must still work."""
    saved(monkeypatch, {"type": "photo", "file_id": "STALE_ID"})
    message = FakeMessage(fail_photo=True)

    await send_start_message(message, "hello", None)

    assert [call[0] for call in message.calls] == ["text"]


async def test_a_broken_gif_id_falls_back_to_plain_text(monkeypatch):
    saved(monkeypatch, {"type": "animation", "file_id": "STALE_ID"})
    message = FakeMessage(fail_animation=True)

    await send_start_message(message, "hello", None)

    assert [call[0] for call in message.calls] == ["text"]
