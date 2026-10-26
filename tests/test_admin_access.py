"""The admin cache and the filter that protects admin-only handlers."""
import pytest

import admin_access
from config import OWNER_ID


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(admin_access, "_admin_ids", set())


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id

    @property
    def from_user(self):
        return self


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = FakeUser(user_id)


async def test_the_owner_is_always_an_admin():
    assert admin_access.is_admin(OWNER_ID) is True


async def test_a_random_user_is_not_an_admin():
    assert admin_access.is_admin(12345) is False


async def test_loading_replaces_the_cached_admin_list(monkeypatch):
    async def get_admin_ids():
        return [123, 456]

    monkeypatch.setattr(admin_access, "get_admin_ids", get_admin_ids)
    admin_access._admin_ids.add(999)

    await admin_access.load_admins()

    assert admin_access.is_admin(123) is True
    assert admin_access.is_admin(456) is True
    assert admin_access.is_admin(999) is False
    assert admin_access.is_admin(OWNER_ID) is True


async def test_adding_an_admin_updates_the_cache_and_the_database(monkeypatch):
    saved = []

    async def db_add_admin(user_id, username=None):
        saved.append((user_id, username))

    monkeypatch.setattr(admin_access, "db_add_admin", db_add_admin)

    await admin_access.add_admin(123, "someone")

    assert saved == [(123, "someone")]
    assert admin_access.is_admin(123) is True


async def test_removing_an_admin_updates_the_cache_and_the_database(monkeypatch):
    removed = []

    async def db_del_admin(user_id):
        removed.append(user_id)
        return True

    monkeypatch.setattr(admin_access, "db_del_admin", db_del_admin)
    admin_access._admin_ids.add(123)

    assert await admin_access.remove_admin(123) is True

    assert removed == [123]
    assert admin_access.is_admin(123) is False


async def test_the_owner_cannot_be_removed(monkeypatch):
    called = False

    async def db_del_admin(user_id):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(admin_access, "db_del_admin", db_del_admin)

    assert await admin_access.remove_admin(OWNER_ID) is False
    assert called is False
    assert admin_access.is_admin(OWNER_ID) is True


async def test_the_admin_filter_matches_the_owner():
    assert await admin_access.admin_filter(None, FakeMessage(OWNER_ID)) is True


async def test_the_admin_filter_matches_a_cached_admin():
    admin_access._admin_ids.add(123)

    assert await admin_access.admin_filter(None, FakeMessage(123)) is True


async def test_the_admin_filter_rejects_a_regular_user():
    assert await admin_access.admin_filter(None, FakeMessage(999)) is False


async def test_the_admin_filter_rejects_an_update_without_a_user():
    class NoUser:
        from_user = None

    assert await admin_access.admin_filter(None, NoUser()) is False
