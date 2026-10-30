#(©)CodeXBotz

import os
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, MediaCaptionTooLong

from bot import Bot
from config import FORCE_SUB_CHANNELS, OWNER_ID, FORCE_MSG, START_MSG, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, PROTECT_CONTENT, AUTO_DELETE_TIME, AUTO_DELETE_MSG, JOIN_REQUEST_ENABLE, LOGGER
from helper_func import subscribed, decode, get_messages, delete_file, get_missing_fsub_channels, shorten_caption, send_start_message
from telegram_trouble import TELEGRAM_TROUBLE, FORCE_SUB_FAIL_OPEN, CHECK_TIMEOUT, RECHECK_AFTER, outage
from database.database import add_user, del_user, full_userbase


async def copy_to_user(msg, user_id, caption, reply_markup):
    """Copy one DB-channel post to the user.

    A bot may only send captions of up to 1024 characters, but posts made by a
    Premium account can carry up to 2048. Telegram refuses those with
    MEDIA_CAPTION_TOO_LONG, which used to mean the file was never delivered.
    Now the file is sent with the caption trimmed to fit instead.
    """
    async def send(cap):
        return await msg.copy(chat_id=user_id, caption=cap, parse_mode=ParseMode.HTML, reply_markup=reply_markup, protect_content=PROTECT_CONTENT)

    try:
        return await send(caption)
    except MediaCaptionTooLong:
        pass

    tried = {caption}
    for cap in (shorten_caption(caption), shorten_caption(caption, 512), ""):
        if cap in tried:
            continue                      # trimming changed nothing, don't repeat the same request
        tried.add(cap)
        try:
            return await send(cap)
        except MediaCaptionTooLong:
            continue
    return None


FSUB_UNAVAILABLE_MSG = (
    "⚠️ <b>I can't check whether you have joined the channels right now.</b>\n\n"
    "Please wait a minute, then press <b>Try Again</b>."
)

FILES_FAILED_MSG = (
    "⚠️ <b>{count} {noun} could not be sent.</b>\n\n"
    "Please wait a minute, then press <b>Try Again</b>."
)


def try_again_markup(client, message):
    """One "Try Again" button that opens the same /start link again (or a plain /start)."""
    username = getattr(client, "username", None)
    if not username:
        return None
    command = getattr(message, "command", None) or []
    payload = command[1] if len(command) > 1 else "start"
    return InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", url=f"https://t.me/{username}?start={payload}")]])


async def notify(message, text, reply_markup=None):
    """Tell the user something. While Telegram is in trouble even this can fail, and that must not become a traceback."""
    try:
        await message.reply_text(text, reply_markup=reply_markup, quote=True, disable_web_page_preview=True)
    except (UserIsBlocked, InputUserDeactivated):
        pass
    except Exception as e:
        LOGGER(__name__).warning("Could not send a notice to user %s: %s", message.from_user.id, str(e) or repr(e))


def log_fsub_failure(user_id, error):
    """One quiet line when Telegram could not answer, the full traceback for anything else."""
    if isinstance(error, TELEGRAM_TROUBLE):
        LOGGER(__name__).warning("Force-sub check: Telegram could not answer for user %s: %s", user_id, str(error) or repr(error) or type(error).__name__)
    else:
        LOGGER(__name__).error("Force-sub check failed for user %s", user_id, exc_info=error)


async def _safe_subscribed(_, client, message):
    """The `subscribed` filter, made to cope with Telegram not being able to answer.

    The membership check itself (helper_func.subscribed) is untouched, and it
    decides as before whenever Telegram answers. What changes is what happens when
    Telegram cannot answer it (its servers are down for everybody, or the lookup
    takes longer than CHECK_TIMEOUT):

    * people are let through, so they get their files (FORCE_SUB_FAIL_OPEN=0 turns
      this off: then they are asked to try again instead);
    * for RECHECK_AFTER seconds after a failure nobody is looked up at all, so the
      next people do not each wait for the same failure;
    * any other error (wrong channel ID, bot not admin there, a bug) is NOT an
      outage: it is logged with its traceback and nobody is let through, so a
      misconfiguration cannot silently switch force-sub off.

    Before, any of these raised inside the filter, Pyrofork logged a traceback and
    treated it as "no match", the not_joined handler asked Telegram a second time,
    failed again, and the user got no reply at all.
    """
    user_id = message.from_user.id if message.from_user else None

    if FORCE_SUB_FAIL_OPEN and outage.active():
        return True

    try:
        result = await asyncio.wait_for(subscribed(client, message), timeout=CHECK_TIMEOUT)
    except TELEGRAM_TROUBLE as e:
        if FORCE_SUB_FAIL_OPEN:
            if outage.start(RECHECK_AFTER):
                LOGGER(__name__).warning(
                    "Force-sub check: Telegram could not answer for user %s (%s). Letting people through "
                    "without checking until it answers again.", user_id, str(e) or type(e).__name__)
            return True
        log_fsub_failure(user_id, e)
        message._fsub_unavailable = True
        return False
    except Exception as e:
        log_fsub_failure(user_id, e)
        message._fsub_unavailable = True
        return False

    if outage.ok():
        LOGGER(__name__).info("Force-sub check: Telegram answers again, checking everyone as usual.")
    return result


safe_subscribed = filters.create(_safe_subscribed)


@Bot.on_message(filters.command('start') & filters.private & safe_subscribed)
async def start_command(client: Client, message: Message):
    id = message.from_user.id
    try:
        # The username is saved too, so the owner can use /addadmin @username.
        await add_user(id, message.from_user.username)
    except Exception:
        pass
    text = message.text
    # "/start start" (the Try Again link for people with no file payload) must
    # behave exactly like a plain /start instead of being decoded as a file link.
    if len(text)>7 and text.split(" ", 1)[-1].strip().lower() != "start":
        try:
            base64_string = text.split(" ", 1)[1]
        except:
            return
        try:
            string = await decode(base64_string)
        except Exception:
            # not a link this bot made (cut off or garbled by the app it was shared in)
            try:
                await message.reply_text("Something went wrong..!")
            except (UserIsBlocked, InputUserDeactivated):
                pass
            return
        argument = string.split("-")
        if len(argument) == 3:
            try:
                start = int(int(argument[1]) / abs(client.db_channel.id))
                end = int(int(argument[2]) / abs(client.db_channel.id))
            except:
                return
            if start <= end:
                ids = range(start,end+1)
            else:
                ids = []
                i = start
                while True:
                    ids.append(i)
                    i -= 1
                    if i < end:
                        break
        elif len(argument) == 2:
            try:
                ids = [int(int(argument[1]) / abs(client.db_channel.id))]
            except:
                return
        try:
            temp_msg = await message.reply("Please wait...")
        except (UserIsBlocked, InputUserDeactivated):
            return
        except FloodWait as e:
            await asyncio.sleep(e.value)      # only a cosmetic message: wait, then carry on without it
            temp_msg = None
        except TELEGRAM_TROUBLE as e:
            LOGGER(__name__).warning("Could not send the 'Please wait' message: %s", str(e) or repr(e))
            temp_msg = None                   # cosmetic too: carry on without it
        try:
            messages = await get_messages(client, ids)
        except:
            await message.reply_text("Something went wrong..!")
            return
        if temp_msg:
            try:
                await temp_msg.delete()
            except Exception:
                pass                          # cosmetic: a leftover "Please wait..." must not stop the files

        track_msgs = []
        failed = 0                            # files Telegram would not take, so the user can be told

        for msg in messages:

            if bool(CUSTOM_CAPTION) & bool(msg.document):
                caption = CUSTOM_CAPTION.format(previouscaption = "" if not msg.caption else msg.caption.html, filename = msg.document.file_name)
            else:
                caption = "" if not msg.caption else msg.caption.html

            if DISABLE_CHANNEL_BUTTON:
                reply_markup = msg.reply_markup
            else:
                reply_markup = None

            try:
                copied_msg = await copy_to_user(msg, message.from_user.id, caption, reply_markup)
            except FloodWait as e:
                # Telegram asked us to slow down: wait, then try this file once more
                await asyncio.sleep(e.value)
                try:
                    copied_msg = await copy_to_user(msg, message.from_user.id, caption, reply_markup)
                except (UserIsBlocked, InputUserDeactivated):
                    return
                except Exception as err:
                    failed += 1
                    LOGGER(__name__).warning("Could not send message %s to user %s: %s", msg.id, message.from_user.id, str(err) or repr(err))
                    continue
            except (UserIsBlocked, InputUserDeactivated):
                # the user blocked the bot (or deleted the account): nothing more to send
                return
            except Exception as e:
                failed += 1
                LOGGER(__name__).warning("Could not send message %s to user %s: %s", msg.id, message.from_user.id, str(e) or repr(e))
                continue

            if not copied_msg:
                continue                      # empty/deleted post in the DB channel (Pyrofork logs it already)

            if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:
                track_msgs.append(copied_msg)

        if failed:
            await notify(
                message,
                FILES_FAILED_MSG.format(count=failed, noun="file" if failed == 1 else "files"),
                try_again_markup(client, message),
            )

        if track_msgs:
            delete_data = await client.send_message(
                chat_id=message.from_user.id,
                text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
            )
            # Schedule the file deletion task after all messages have been copied
            asyncio.create_task(delete_file(track_msgs, client, delete_data))

        return
    else:
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("😊 About Me", callback_data = "about"),
                    InlineKeyboardButton("🔒 Close", callback_data = "close")
                ]
            ]
        )
        # The start media (image or GIF) is whatever the owner picked with
        # /smedia; it is stored in the database, so it survives a restart.
        await send_start_message(
            message,
            START_MSG.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name,
                username=None if not message.from_user.username else '@' + message.from_user.username,
                mention=message.from_user.mention,
                id=message.from_user.id
            ),
            reply_markup
        )
        return

    
#=====================================================================================##

WAIT_MSG = """"<b>Processing ...</b>"""

REPLY_ERROR = """<code>Use this command as a replay to any telegram message with out any spaces.</code>"""

#=====================================================================================##


@Bot.on_message(filters.command('start') & filters.private)
async def not_joined(client: Client, message: Message):

    user_id = message.from_user.id
    if getattr(message, "_fsub_unavailable", False):
        # The filter above could not get an answer from Telegram a moment ago.
        # Asking again right away would only fail again: say so instead.
        await notify(message, FSUB_UNAVAILABLE_MSG, try_again_markup(client, message))
        return
    try:
        missing_channels = await get_missing_fsub_channels(client, user_id)
    except Exception as e:
        # Telegram stopped answering between the filter and now.
        log_fsub_failure(user_id, e)
        await notify(message, FSUB_UNAVAILABLE_MSG, try_again_markup(client, message))
        return

    join_buttons = []
    for channel_id in missing_channels:
        info = getattr(client, "force_sub_info", {}).get(channel_id, {})
        title = info.get("title") or "Channel"
        channel_url = info.get("link")

        # Re-fetch the chat to get the current title — the channel may have
        # been renamed after the bot started, and force_sub_info is only
        # populated once at startup.
        try:
            chat = await client.get_chat(channel_id)
            if chat.title:
                title = chat.title
        except Exception:
            pass  # fall back to the cached title above

        if bool(JOIN_REQUEST_ENABLE):
            try:
                invite = await client.create_chat_invite_link(
                    chat_id=channel_id,
                    creates_join_request=True
                )
                channel_url = invite.invite_link
            except Exception:
                pass  # fall back to the stored invite link, if any

        if not channel_url:
            # Startup couldn't resolve this channel (e.g. brand-new channel the
            # bot hadn't seen yet). Try again now that it may be cached.
            try:
                channel_url = await client.export_chat_invite_link(channel_id)
                client.force_sub_info[channel_id] = {"link": channel_url, "title": title}
            except Exception:
                pass

        if not channel_url:
            continue  # can't build a usable button for this channel, skip it

        # Fixed button labels by channel position (FORCE_SUB_CHANNEL, 2, 3).
        labels = ["News Channel", "Index Channel", "Backup Channel"]
        try:
            label = labels[FORCE_SUB_CHANNELS.index(channel_id)]
        except (ValueError, IndexError):
            label = title

        join_buttons.append(
            InlineKeyboardButton(
                f"Join {label}",
                url=channel_url
            )
        )

    # Lay out two join buttons per row, side by side.
    buttons = [join_buttons[i:i + 2] for i in range(0, len(join_buttons), 2)]

    try:
        try_again_url = f"https://t.me/{client.username}?start={message.command[1]}"
    except IndexError:
        # Plain /start with no file payload to retry — just relink to a bare
        # /start so the button is never missing.
        try_again_url = f"https://t.me/{client.username}?start=start"

    buttons.append(
        [
            InlineKeyboardButton(
                text = 'Try Again',
                url = try_again_url
            )
        ]
    )

    try:
        await message.reply(
            text = FORCE_MSG.format(
                    first = message.from_user.first_name,
                    last = message.from_user.last_name,
                    username = None if not message.from_user.username else '@' + message.from_user.username,
                    mention = message.from_user.mention,
                    id = message.from_user.id
                ),
            reply_markup = InlineKeyboardMarkup(buttons),
            quote = True,
            disable_web_page_preview = True
        )
    except (UserIsBlocked, InputUserDeactivated):
        pass  # the user blocked the bot meanwhile

@Bot.on_message(filters.command('users') & filters.private & filters.user([OWNER_ID]))
async def get_users(client: Bot, message: Message):
    msg = await client.send_message(chat_id=message.chat.id, text=WAIT_MSG)
    users = await full_userbase()
    await msg.edit(f"{len(users)} users are using this bot")

@Bot.on_message(filters.private & filters.command('broadcast') & filters.user([OWNER_ID]))
async def send_text(client: Bot, message: Message):
    if message.reply_to_message:
        query = await full_userbase()
        broadcast_msg = message.reply_to_message
        total = 0
        successful = 0
        blocked = 0
        deleted = 0
        unsuccessful = 0
        
        pls_wait = await message.reply("<i>Broadcasting Message.. This will Take Some Time</i>")
        for chat_id in query:
            try:
                await broadcast_msg.copy(chat_id)
                successful += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await broadcast_msg.copy(chat_id)
                successful += 1
            except UserIsBlocked:
                await del_user(chat_id)
                blocked += 1
            except InputUserDeactivated:
                await del_user(chat_id)
                deleted += 1
            except:
                unsuccessful += 1
                pass
            total += 1
        
        status = f"""<b><u>Broadcast Completed</u>

Total Users: <code>{total}</code>
Successful: <code>{successful}</code>
Blocked Users: <code>{blocked}</code>
Deleted Accounts: <code>{deleted}</code>
Unsuccessful: <code>{unsuccessful}</code></b>"""
        
        return await pls_wait.edit(status)

    else:
        msg = await message.reply(REPLY_ERROR)
        await asyncio.sleep(8)
        await msg.delete()
