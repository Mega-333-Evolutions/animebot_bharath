#(©)Codexbotz

from bot import Bot
from pyrogram.types import Message
from pyrogram import filters
from admin_access import admin_filter
from config import BOT_STATS_TEXT, OWNER_ID, USER_REPLY_TEXT
from datetime import datetime
import time
from helper_func import get_readable_time, not_command

@Bot.on_message(filters.command('stats') & filters.user([OWNER_ID]))
async def stats(bot: Bot, message: Message):
    now = datetime.now()
    delta = now - bot.uptime
    # delta.seconds only gets the leftover seconds within the current day
    # (0-86399) — once uptime crosses 24h, .days increments and .seconds
    # resets, making uptime look like it restarted. total_seconds() gives
    # the true elapsed time regardless of how many days have passed.
    uptime_str = get_readable_time(int(delta.total_seconds()))

    ping_start = time.monotonic()
    await bot.get_me()
    ping_ms = round((time.monotonic() - ping_start) * 1000)

    await message.reply(BOT_STATS_TEXT.format(uptime=uptime_str, ping=ping_ms))

# Only the first matching handler of a group is run, and the handlers are
# registered in the order the plugin files are walked. This catch-all must
# therefore leave commands alone, or it answers them before the handler that
# belongs to them ever gets to see them.
@Bot.on_message(filters.private & filters.incoming & not_command & ~admin_filter)
async def useless(_,message: Message):
    if USER_REPLY_TEXT:
        await message.reply(USER_REPLY_TEXT)
