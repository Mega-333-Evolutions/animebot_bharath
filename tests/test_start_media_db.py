"""The start media must live in the database, so a restart does not wipe it."""
import pytest
from mongomock_motor import AsyncMongoMockClient

from database import database as db


@pytest.fixture
def collection(monkeypatch):
    """Point the start_media collection at an in-memory Mongo."""
    client = AsyncMongoMockClient()
    col = client["filesharexbot"]["start_media"]
    monkeypatch.setattr(db, "start_media_data", col)
    return col


async def test_nothing_is_saved_initially(collection):
    assert await db.get_start_media() is None


async def test_saved_media_is_read_back(collection):
    await db.set_start_media("photo", "FILE_ID_1")

    assert await db.get_start_media() == {"type": "photo", "file_id": "FILE_ID_1"}


async def test_saving_again_replaces_the_previous_media(collection):
    await db.set_start_media("photo", "FILE_ID_1")
    await db.set_start_media("animation", "FILE_ID_2")

    assert await db.get_start_media() == {"type": "animation", "file_id": "FILE_ID_2"}


async def test_removing_the_media_clears_it(collection):
    await db.set_start_media("photo", "FILE_ID_1")
    await db.del_start_media()

    assert await db.get_start_media() is None


async def test_removing_when_nothing_is_saved_is_harmless(collection):
    await db.del_start_media()

    assert await db.get_start_media() is None


async def test_the_media_is_read_from_the_database_not_from_memory(collection):
    """A restart means a fresh process: the media has to come back out of Mongo."""
    await collection.insert_one(
        {"_id": "current", "type": "animation", "file_id": "FROM_DB"}
    )

    assert await db.get_start_media() == {"type": "animation", "file_id": "FROM_DB"}
