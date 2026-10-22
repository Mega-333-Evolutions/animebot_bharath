#(©)CodeXBotz
"""Owner-only command to set the image or GIF the bot answers /start with.

The media is kept in the database, so it survives a restart of the bot.
"""

import asyncio
import os
import shutil
import tempfile
import time

from bot import Bot  # imported first: it pulls in pyromod, which adds ListenerCanceled
from config import ASK_TIMEOUT, LOGGER, MEDIA_NAMES, OWNER_ID
from database.database import del_start_media, get_start_media, set_start_media

from pyrogram import Client, filters
from pyrogram.errors import ListenerCanceled, MessageNotModified, RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

OWNER = [OWNER_ID]

# Everything the owner might send us while we are waiting for the media.
MEDIA_FILTER = filters.photo | filters.animation | filters.document


async def smedia_callback_filter(_, __, query):
    """Only the /smedia menu's own buttons."""
    return bool(query.data) and query.data.startswith("sm_")


smedia_cb_filter = filters.create(smedia_callback_filter)


def media_from_message(message):
    """Return (media_type, file_id) for media we can use as it is.

    Documents are left out on purpose: Telegram ties a file_id to the type of
    media it was uploaded as, so the id of a file cannot be sent as a photo.
    """
    if message.photo:
        return "photo", message.photo.file_id
    if message.animation:
        return "animation", message.animation.file_id
    return None, None


def document_media_type(document):
    """Return "photo" / "animation" for a file we can upload again, else None."""
    if document is None:
        return None

    mime_type = (document.mime_type or "").lower()
    if mime_type.startswith("image/"):
        return "photo"
    if mime_type == "video/mp4":
        return "animation"
    return None


async def reupload_file(client, chat_id, message, media_type):
    """Download a file the owner sent and send it back as a photo or a GIF.

    A file has to be uploaded again to get an id of the right type. Returns
    (media_type, file_id), or None when that did not work out.
    """
    temp_dir = tempfile.mkdtemp(prefix="smedia_")
    try:
        try:
            path = await client.download_media(
                message, file_name=os.path.join(temp_dir, "media")
            )
            if not path or not os.path.isfile(path):
                return None

            if media_type == "photo":
                sent = await client.send_photo(chat_id=chat_id, photo=path)
                return "photo", sent.photo.file_id

            sent = await client.send_animation(chat_id=chat_id, animation=path)
            return "animation", sent.animation.file_id
        except RPCError as e:
            LOGGER(__name__).warning("Could not upload the start media: %s", e)
            return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def wait_for_media(client, chat_id, deadline):
    """Wait for the owner to send the start media.

    Returns (media_type, file_id) once something usable has arrived, or None
    when the owner ran out of time. A file is uploaded again so that it can be
    used as a photo or a GIF; a file that is neither is refused and the bot
    keeps waiting.
    """
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None

        try:
            response = await client.listen(chat_id, MEDIA_FILTER, timeout=remaining)
        except asyncio.TimeoutError:
            return None

        media_type, file_id = media_from_message(response)
        if media_type:
            return media_type, file_id

        document_type = document_media_type(response.document)
        if not document_type:
            await response.reply(
                "<b>❌ That is not an image or a GIF.</b>\n\nSend it again, please."
            )
            continue

        reuploaded = await reupload_file(client, chat_id, response, document_type)
        if reuploaded:
            return reuploaded

        await response.reply(
            "<b>❌ Could not use that file.</b>\n\n"
            "Send it as a normal photo or GIF instead."
        )


async def build_menu():
    """Build the /smedia menu (text and keyboard) from what is saved right now."""
    current = await get_start_media()

    buttons = [[
        InlineKeyboardButton("📷 Set Start Image", callback_data="sm_image"),
        InlineKeyboardButton("🎬 Set Start GIF", callback_data="sm_gif"),
    ]]
    if current:
        buttons.append([
            InlineKeyboardButton("🗑 Remove Current", callback_data="sm_del")
        ])
    buttons.append([
        InlineKeyboardButton("❌ Close", callback_data="sm_close")
    ])

    if current:
        label = MEDIA_NAMES.get(current.get("type"), "unknown")
    else:
        label = "❌ None set (plain text start)"

    text = (
        "<b>⚙️ Start Media Settings</b>\n\n"
        f"Current start media: <b>{label}</b>\n\n"
        "Choose what you want to set as the start media 👇"
    )
    return text, InlineKeyboardMarkup(buttons)


async def refresh_menu(query, notice=""):
    """Redraw the menu, so it shows the media that is saved right now."""
    text, markup = await build_menu()
    if notice:
        text = f"{notice}\n\n{text}"

    try:
        await query.message.edit_text(text, reply_markup=markup)
    except MessageNotModified:
        pass
    except Exception as e:
        LOGGER(__name__).warning("Could not refresh the /smedia menu: %s", e)


@Bot.on_message(filters.command("smedia") & filters.private & filters.user(OWNER))
async def smedia_cmd(client: Client, message: Message):
    text, markup = await build_menu()
    await message.reply(text, reply_markup=markup, quote=True)


@Bot.on_callback_query(smedia_cb_filter & filters.user(OWNER))
async def smedia_cb(client: Client, query: CallbackQuery):
    data = query.data
    chat_id = query.message.chat.id

    if data in ("sm_image", "sm_gif"):
        await query.answer()
        want = "photo" if data == "sm_image" else "animation"
        prompt = await client.send_message(
            chat_id,
            f"Send me the <b>{MEDIA_NAMES[want]}</b> you want as the start media now."
            "\n\n<i>(Sending it as a file works too.)</i>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="sm_cancel")]
            ]),
        )

        deadline = time.monotonic() + ASK_TIMEOUT
        try:
            result = await wait_for_media(client, chat_id, deadline)
        except ListenerCanceled:
            await _safe_edit(prompt, "❌ Cancelled.")
            return

        if result is None:
            await _safe_delete(prompt)
            await refresh_menu(query, "⏱️ Timed out — nothing was changed.")
            return

        media_type, file_id = result
        await set_start_media(media_type, file_id)
        await _safe_delete(prompt)

        notice = (
            "✅ Saved! The start media is now "
            f"<b>{MEDIA_NAMES.get(media_type, media_type)}</b>."
        )
        if media_type != want:
            notice += (
                f"\n\n⚠️ You asked for {MEDIA_NAMES[want]} but sent "
                f"{MEDIA_NAMES.get(media_type, media_type)} — saved as that."
            )
        await refresh_menu(query, notice)
        return

    if data == "sm_cancel":
        await query.answer("Cancelled")
        client.cancel_listener(chat_id)
        return

    if data == "sm_del":
        await del_start_media()
        await query.answer("Start media removed")
        await refresh_menu(query, "🗑 Start media removed.")
        return

    if data == "sm_close":
        await query.answer()
        client.cancel_listener(chat_id)
        await _safe_delete(query.message)


async def _safe_delete(message):
    """Delete a message, ignoring the case where it is already gone."""
    try:
        await message.delete()
    except Exception as e:
        LOGGER(__name__).warning("Could not delete a message: %s", e)


async def _safe_edit(message, text):
    """Edit a message, ignoring the case where it cannot be edited."""
    try:
        await message.edit_text(text)
    except Exception as e:
        LOGGER(__name__).warning("Could not edit a message: %s", e)
