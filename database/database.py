#(©)CodeXBotz

from motor.motor_asyncio import AsyncIOMotorClient
from config import DB_URI, DB_NAME

dbclient = AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
user_data = database['users']
start_media_data = database['start_media']


async def present_user(user_id: int) -> bool:
    found = await user_data.find_one({'_id': user_id})
    return bool(found)


async def add_user(user_id: int):
    await user_data.insert_one({'_id': user_id})
    return


async def full_userbase():
    user_ids = []
    async for doc in user_data.find({}, {'_id': 1}):
        user_ids.append(doc['_id'])
    return user_ids


async def del_user(user_id: int):
    await user_data.delete_one({'_id': user_id})
    return


# ── Start media ──────────────────────────────────────────────────────────────
# The image or GIF the owner picked with /smedia. It is kept in the database
# rather than in an environment variable, so it is still there after a restart.


async def get_start_media():
    """Return the saved start media as {"type": ..., "file_id": ...}, or None."""
    doc = await start_media_data.find_one({'_id': 'current'})
    if not doc:
        return None
    return {'type': doc.get('type'), 'file_id': doc.get('file_id')}


async def set_start_media(media_type: str, file_id: str):
    """Save the start media, replacing whatever was saved before."""
    await start_media_data.replace_one(
        {'_id': 'current'},
        {'_id': 'current', 'type': media_type, 'file_id': file_id},
        upsert=True,
    )
    return


async def del_start_media():
    """Remove the saved start media."""
    await start_media_data.delete_one({'_id': 'current'})
    return
