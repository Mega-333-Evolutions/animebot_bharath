"""A user's username is stored on /start so /addadmin @username can find them."""
from plugins import start


class FakeUser:
    id = 42
    username = "SomeOne"
    first_name = "Some"
    last_name = "One"
    mention = "@SomeOne"


class FakeMessage:
    text = "/start"
    from_user = FakeUser()


async def test_start_saves_the_users_username(monkeypatch):
    saved = []

    async def add_user(user_id, username=None):
        saved.append((user_id, username))

    async def present_user(user_id):
        return False

    async def send_start_message(message, text, markup):
        return None

    monkeypatch.setattr(start, "add_user", add_user)
    monkeypatch.setattr(start, "present_user", present_user, raising=False)
    monkeypatch.setattr(start, "send_start_message", send_start_message)

    await start.start_command(None, FakeMessage())

    assert saved == [(42, "SomeOne")]
