"""The owner-facing /addadmin and /deladmin commands."""
import pytest

from config import OWNER_ID
from plugins import admin


class FakeMessage:
    def __init__(self, *args):
        self.command = ["addadmin", *args]
        self.text = "/" + " ".join(self.command)
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return self


@pytest.fixture
def calls(monkeypatch):
    """Replace the database/cache functions the commands use."""
    state = {
        "admins": set(),
        "saved": [],
        "removed": [],
        "lookups": [],
        "added": [],
    }

    def is_admin(user_id):
        return user_id == OWNER_ID or user_id in state["admins"]

    async def add_admin(user_id, username=None):
        state["added"].append((user_id, username))

    async def remove_admin(user_id):
        state["removed"].append(user_id)
        return True

    async def find_user_by_username(username):
        state["lookups"].append(username)
        return state["saved"].pop(0) if state["saved"] else None

    monkeypatch.setattr(admin, "is_admin", is_admin)
    monkeypatch.setattr(admin, "add_admin", add_admin)
    monkeypatch.setattr(admin, "remove_admin", remove_admin)
    monkeypatch.setattr(admin, "find_user_by_username", find_user_by_username)
    return state


async def test_the_owner_can_add_an_admin_by_user_id(calls):
    message = FakeMessage("123")

    await admin.addadmin_cmd(None, message)

    assert calls["added"] == [(123, None)]
    assert "admin" in message.replies[-1].lower()


async def test_the_owner_can_add_an_admin_by_username(calls):
    calls["saved"].append(42)
    message = FakeMessage("@SomeOne")

    await admin.addadmin_cmd(None, message)

    assert calls["lookups"] == ["SomeOne"]
    assert calls["added"] == [(42, "SomeOne")]
    assert "admin" in message.replies[-1].lower()


async def test_a_username_without_the_at_sign_also_works(calls):
    calls["saved"].append(42)
    message = FakeMessage("someone")

    await admin.addadmin_cmd(None, message)

    assert calls["lookups"] == ["someone"]
    assert calls["added"] == [(42, "someone")]


async def test_an_unknown_username_is_refused(calls):
    message = FakeMessage("@nobody")

    await admin.addadmin_cmd(None, message)

    assert calls["added"] == []
    reply = message.replies[-1].lower()
    assert "start" in reply
    assert "user id" in reply


async def test_the_owner_cannot_be_added_as_an_admin(calls):
    message = FakeMessage(str(OWNER_ID))

    await admin.addadmin_cmd(None, message)

    assert calls["added"] == []
    assert "owner" in message.replies[-1].lower()


async def test_an_existing_admin_is_not_added_twice(calls):
    calls["admins"].add(123)
    message = FakeMessage("123")

    await admin.addadmin_cmd(None, message)

    assert calls["added"] == []
    assert "already" in message.replies[-1].lower()


async def test_addadmin_without_an_argument_shows_usage(calls):
    message = FakeMessage()

    await admin.addadmin_cmd(None, message)

    assert calls["added"] == []
    assert "/addadmin" in message.replies[-1]


async def test_the_owner_can_remove_an_admin_by_user_id(calls):
    calls["admins"].add(123)
    message = FakeMessage("123")
    message.command[0] = "deladmin"

    await admin.deladmin_cmd(None, message)

    assert calls["removed"] == [123]
    assert "removed" in message.replies[-1].lower()


async def test_the_owner_can_remove_an_admin_by_username(calls):
    calls["admins"].add(42)
    calls["saved"].append(42)
    message = FakeMessage("@someone")
    message.command[0] = "deladmin"

    await admin.deladmin_cmd(None, message)

    assert calls["lookups"] == ["someone"]
    assert calls["removed"] == [42]


async def test_the_owner_cannot_be_removed(calls):
    message = FakeMessage(str(OWNER_ID))
    message.command[0] = "deladmin"

    await admin.deladmin_cmd(None, message)

    assert calls["removed"] == []
    assert "owner" in message.replies[-1].lower()


async def test_removing_someone_who_is_not_an_admin_is_refused(calls):
    message = FakeMessage("123")
    message.command[0] = "deladmin"

    await admin.deladmin_cmd(None, message)

    assert calls["removed"] == []
    assert "isn't an admin" in message.replies[-1].lower()


async def test_deladmin_with_an_unknown_username_is_refused(calls):
    message = FakeMessage("@nobody")
    message.command[0] = "deladmin"

    await admin.deladmin_cmd(None, message)

    assert calls["removed"] == []
    assert "start" in message.replies[-1].lower()


async def test_deladmin_without_an_argument_shows_usage(calls):
    message = FakeMessage()
    message.command[0] = "deladmin"

    await admin.deladmin_cmd(None, message)

    assert calls["removed"] == []
    assert "/deladmin" in message.replies[-1]
