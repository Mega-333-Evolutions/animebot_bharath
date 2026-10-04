#(©)CodeXBotz

import os
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated

from bot import Bot
from config import FORCE_SUB_CHANNELS, ADMINS, FORCE_MSG, START_MSG, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, PROTECT_CONTENT, START_PIC, AUTO_DELETE_TIME, AUTO_DELETE_MSG, JOIN_REQUEST_ENABLE
from helper_func import subscribed, decode, get_messages, delete_file, get_missing_fsub_channels
from database.database import add_user, del_user, full_userbase, present_user


@Bot.on_message(filters.command('start') & filters.private & subscribed)
async def start_command(client: Client, message: Message):
    id = message.from_user.id
    if not await present_user(id):
        try:
            await add_user(id)
        except:
            pass
    text = message.text
    # "/start start" (the Try Again link for people with no file payload) must
    # behave exactly like a plain /start instead of being decoded as a file link.
    if len(text)>7 and text.split(" ", 1)[-1].strip().lower() != "start":
        try:
            base64_string = text.split(" ", 1)[1]
        except:
            return
        string = await decode(base64_string)
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
        except UserIsBlocked:
            return
        try:
            messages = await get_messages(client, ids)
        except:
            await message.reply_text("Something went wrong..!")
            return
        await temp_msg.delete()

        track_msgs = []

        for msg in messages:

            if bool(CUSTOM_CAPTION) & bool(msg.document):
                caption = CUSTOM_CAPTION.format(previouscaption = "" if not msg.caption else msg.caption.html, filename = msg.document.file_name)
            else:
                caption = "" if not msg.caption else msg.caption.html

            if DISABLE_CHANNEL_BUTTON:
                reply_markup = msg.reply_markup
            else:
                reply_markup = None

            if AUTO_DELETE_TIME and AUTO_DELETE_TIME > 0:

                try:
                    copied_msg_for_deletion = await msg.copy(chat_id=message.from_user.id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, protect_content=PROTECT_CONTENT)
                    if copied_msg_for_deletion:
                        track_msgs.append(copied_msg_for_deletion)
                    else:
                        print("Failed to copy message, skipping.")

                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    copied_msg_for_deletion = await msg.copy(chat_id=message.from_user.id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, protect_content=PROTECT_CONTENT)
                    if copied_msg_for_deletion:
                        track_msgs.append(copied_msg_for_deletion)
                    else:
                        print("Failed to copy message after retry, skipping.")

                except Exception as e:
                    print(f"Error copying message: {e}")

            else:
                try:
                    copied_msg = await msg.copy(chat_id=message.from_user.id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, protect_content=PROTECT_CONTENT)
                    if not copied_msg:
                        print("Failed to copy message, skipping.")
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    copied_msg = await msg.copy(chat_id=message.from_user.id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, protect_content=PROTECT_CONTENT)
                    if not copied_msg:
                        print("Failed to copy message after retry, skipping.")
                except Exception as e:
                    print(f"Error copying message: {e}")

        if track_msgs:
            delete_data = await client.send_message(
                chat_id=message.from_user.id,
                text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
            )
            # Schedule the file deletion task after all messages have been copied
            asyncio.create_task(delete_file(track_msgs, client, delete_data))
        else:
            print("No messages to track for deletion.")

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
        if START_PIC:  # Check if START_PIC has a value
            await message.reply_photo(
                photo=START_PIC,
                caption=START_MSG.format(
                    first=message.from_user.first_name,
                    last=message.from_user.last_name,
                    username=None if not message.from_user.username else '@' + message.from_user.username,
                    mention=message.from_user.mention,
                    id=message.from_user.id
                ),
                reply_markup=reply_markup,
                quote=True
            )
        else:  # If START_PIC is empty, send only the text
            await message.reply_text(
                text=START_MSG.format(
                    first=message.from_user.first_name,
                    last=message.from_user.last_name,
                    username=None if not message.from_user.username else '@' + message.from_user.username,
                    mention=message.from_user.mention,
                    id=message.from_user.id
                ),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                quote=True
            )
        return

    
#=====================================================================================##

WAIT_MSG = """"<b>Processing ...</b>"""

REPLY_ERROR = """<code>Use this command as a replay to any telegram message with out any spaces.</code>"""

#=====================================================================================##


@Bot.on_message(filters.command('start') & filters.private)
async def not_joined(client: Client, message: Message):

    user_id = message.from_user.id
    missing_channels = await get_missing_fsub_channels(client, user_id)

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

@Bot.on_message(filters.command('users') & filters.private & filters.user(ADMINS))
async def get_users(client: Bot, message: Message):
    msg = await client.send_message(chat_id=message.chat.id, text=WAIT_MSG)
    users = await full_userbase()
    await msg.edit(f"{len(users)} users are using this bot")

@Bot.on_message(filters.private & filters.command('broadcast') & filters.user(ADMINS))
async def send_text(client: Bot, message: Message):
    if message.from_user.id != 1001484109: 
        return await message.reply("Sorry, only the Bot Owner can use the broadcast command!")
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
                await asyncio.sleep(e.x)
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
