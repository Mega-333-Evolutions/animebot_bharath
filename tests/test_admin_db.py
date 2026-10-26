"""Admins and usernames must live in MongoDB, not in environment variables."""
import pytest
from mongomock_motor import AsyncMongoMockClient

from database import database as db


@pytest.fixture
def collections(monkeypatch):
    """Point the admins/users collections at an in-memory Mongo."""
    client = AsyncMongoMockClient()
    database = client["filesharexbot"]
    admins = database["admins"]
    users = database["users"]
    monkeypatch.setattr(db, "admins_data", admins)
    monkeypatch.setattr(db, "user_data", users)
    return admins, users


async def test_the_admin_list_starts_empty(collections):
    assert await db.get_admin_ids() == []


async def test_an_added_admin_is_persisted(collections):
    admins, _ = collections

    await db.add_admin(123, "someone")

    assert await db.get_admin_ids() == [123]
    saved = await admins.find_one({"_id": 123})
    assert saved["username"] == "someone"


async def test_adding_the_same_admin_twice_keeps_one_entry(collections):
    await db.add_admin(123)
    await db.add_admin(123)

    assert await db.get_admin_ids() == [123]


async def test_a_removed_admin_is_gone(collections):
    await db.add_admin(123)

    assert await db.del_admin(123) is True
    assert await db.get_admin_ids() == []


async def test_removing_an_unknown_admin_reports_false(collections):
    assert await db.del_admin(999) is False


async def test_username_lookup_finds_a_known_user(collections):
    _, users = collections
    await users.insert_one({"_id": 42, "username": "SomeOne", "username_lower": "someone"})

    assert await db.find_user_by_username("someone") == 42
    assert await db.find_user_by_username("@SomeOne") == 42


async def test_username_lookup_returns_none_for_an_unknown_user(collections):
    assert await db.find_user_by_username("nobody") is None


async def test_adding_a_user_saves_the_username(collections):
    _, users = collections

    await db.add_user(42, "SomeOne")

    saved = await users.find_one({"_id": 42})
    assert saved["username"] == "SomeOne"
    assert saved["username_lower"] == "someone"


async def test_adding_an_existing_user_updates_the_username(collections):
    _, users = collections
    await db.add_user(42, "old_name")

    await db.add_user(42, "new_name")

    saved = await users.find_one({"_id": 42})
    assert saved["username"] == "new_name"
    assert saved["username_lower"] == "new_name"
