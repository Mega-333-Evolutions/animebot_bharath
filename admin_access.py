#(©)CodeXBotz
"""The bot's admin list.

Admins are kept in MongoDB and loaded into memory once at startup, so the
handlers do not have to query the database for every message. /addadmin and
/deladmin keep both copies in sync.

OWNER_ID is always an admin and cannot be removed; it is the bootstrap account.
"""

from pyrogram import filters

from config import LOGGER, OWNER_ID
from database.database import (
    add_admin as db_add_admin,
    del_admin as db_del_admin,
    get_admin_ids,
)

_admin_ids = set()


async def load_admins():
    """Load the saved admin list into memory (called once at startup)."""
    try:
        admin_ids = await get_admin_ids()
    except Exception as e:
        LOGGER(__name__).warning("Could not load admins from the database: %s", e)
        return
    _admin_ids.clear()
    _admin_ids.update(admin_ids)


def is_admin(user_id: int) -> bool:
    """True for the owner and for every admin saved in the database."""
    return user_id == OWNER_ID or user_id in _admin_ids


async def add_admin(user_id: int, username: str = None):
    """Save a new admin and make it effective immediately."""
    await db_add_admin(user_id, username)
    _admin_ids.add(user_id)


async def remove_admin(user_id: int) -> bool:
    """Remove an admin. The owner cannot be removed."""
    if user_id == OWNER_ID:
        return False
    removed = await db_del_admin(user_id)
    _admin_ids.discard(user_id)
    return removed


async def _admin_filter(_, __, update) -> bool:
    user = getattr(update, "from_user", None)
    return bool(user and is_admin(user.id))


admin_filter = filters.create(_admin_filter)
