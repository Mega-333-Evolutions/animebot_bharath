#(©)CodeXBotz
"""Owner-only commands that manage the admin list.

Admins are saved in MongoDB (see admin_access.py). The owner is configured with
OWNER_ID and is always an admin, so these commands cannot lock everyone out.
"""

from bot import Bot
from config import LOGGER, OWNER_ID
from admin_access import add_admin, is_admin, remove_admin
from database.database import find_user_by_username

from pyrogram import Client, filters
from pyrogram.types import Message

OWNER = [OWNER_ID]


async def _resolve_target(message: Message):
    """Return (user_id, username, error) for the argument of an admin command."""
    command = message.command[0] if message.command else "addadmin"
    usage = f"Usage: /{command} &lt;user_id or @username&gt;"

    if not message.command or len(message.command) < 2:
        return None, None, usage

    raw = message.command[1].strip().lstrip("@")
    if not raw:
        return None, None, usage

    if raw.isdigit():
        return int(raw), None, None

    user_id = await find_user_by_username(raw)
    if user_id is None:
        return None, raw, (
            f"I don't know @{raw} yet. Ask them to /start the bot first, "
            "or use their numeric user ID."
        )
    return user_id, raw, None


@Bot.on_message(filters.command("addadmin") & filters.private & filters.user(OWNER))
async def addadmin_cmd(client: Client, message: Message):
    user_id, username, error = await _resolve_target(message)
    if error:
        return await message.reply(error)

    if user_id == OWNER_ID:
        return await message.reply("The bot owner is already an admin.")
    if is_admin(user_id):
        return await message.reply("That user is already an admin.")

    try:
        await add_admin(user_id, username)
    except Exception as e:
        LOGGER(__name__).warning("Could not save admin %s: %s", user_id, e)
        return await message.reply("Could not save that admin. Please try again.")

    name = f"@{username}" if username else f"<code>{user_id}</code>"
    await message.reply(f"✅ {name} is now an admin.")


@Bot.on_message(filters.command("deladmin") & filters.private & filters.user(OWNER))
async def deladmin_cmd(client: Client, message: Message):
    user_id, username, error = await _resolve_target(message)
    if error:
        return await message.reply(error)

    if user_id == OWNER_ID:
        return await message.reply("The bot owner can't be removed.")
    if not is_admin(user_id):
        return await message.reply("That user isn't an admin.")

    try:
        removed = await remove_admin(user_id)
    except Exception as e:
        LOGGER(__name__).warning("Could not remove admin %s: %s", user_id, e)
        return await message.reply("Could not remove that admin. Please try again.")

    if not removed:
        return await message.reply("That user isn't an admin.")

    name = f"@{username}" if username else f"<code>{user_id}</code>"
    await message.reply(f"✅ {name} has been removed from the admin list.")
