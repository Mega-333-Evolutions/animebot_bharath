#(©)Codexbotz

import base64
import re
import asyncio
from html import escape as _html_escape
from html.parser import HTMLParser
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from config import FORCE_SUB_CHANNELS, ADMINS, AUTO_DELETE_TIME, AUTO_DEL_SUCCESS_MSG
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
from pyrogram.errors import FloodWait


async def get_missing_fsub_channels(client, user_id):
    """Return the list of configured force-sub channel IDs the user has NOT joined yet."""
    if user_id in ADMINS:
        return []
    missing = []
    for channel_id in FORCE_SUB_CHANNELS:
        try:
            member = await client.get_chat_member(chat_id=channel_id, user_id=user_id)
        except UserNotParticipant:
            missing.append(channel_id)
            continue
        if member.status not in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]:
            missing.append(channel_id)
    return missing


async def is_subscribed(filter, client, update):
    if not FORCE_SUB_CHANNELS:
        return True
    user_id = update.from_user.id
    missing = await get_missing_fsub_channels(client, user_id)
    return len(missing) == 0

async def encode(string):
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = (base64_bytes.decode("ascii")).strip("=")
    return base64_string

async def decode(base64_string):
    base64_string = base64_string.strip("=") # links generated before this commit will be having = sign, hence striping them to handle padding errors.
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes) 
    string = string_bytes.decode("ascii")
    return string

async def get_messages(client, message_ids):
    messages = []
    total_messages = 0
    while total_messages != len(message_ids):
        temb_ids = message_ids[total_messages:total_messages+200]
        try:
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=temb_ids
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=temb_ids
            )
        except:
            pass
        total_messages += len(temb_ids)
        messages.extend(msgs)
    return messages

async def get_message_id(client, message):
    if message.forward_from_chat:
        if message.forward_from_chat.id == client.db_channel.id:
            return message.forward_from_message_id
        else:
            return 0
    elif message.forward_sender_name:
        return 0
    elif message.text:
        pattern = "https://t.me/(?:c/)?(.*)/(\d+)"
        matches = re.match(pattern,message.text)
        if not matches:
            return 0
        channel_id = matches.group(1)
        msg_id = int(matches.group(2))
        if channel_id.isdigit():
            if f"-100{channel_id}" == str(client.db_channel.id):
                return msg_id
        else:
            if channel_id == client.db_channel.username:
                return msg_id
    else:
        return 0

def get_readable_time(seconds: int) -> str:
    seconds = int(seconds)
    periods = [
        ("y", 365 * 86400),
        ("mo", 30 * 86400),
        ("w", 7 * 86400),
        ("d", 86400),
        ("h", 3600),
        ("m", 60),
    ]
    remainder = seconds
    parts = []
    for suffix, length in periods:
        value, remainder = divmod(remainder, length)
        if value > 0:
            parts.append(f"{value}{suffix}")
    parts.append(f"{remainder}s")  # seconds is always shown, even if 0
    return ":".join(parts)

async def delete_file(messages, client, process):
    await asyncio.sleep(AUTO_DELETE_TIME)
    for msg in messages:
        try:
            await client.delete_messages(chat_id=msg.chat.id, message_ids=[msg.id])
        except FloodWait as e:
            await asyncio.sleep(e.value)
            print(f"The attempt to delete the media {msg.id} was unsuccessful: {e}")
        except Exception as e:
            print(f"The attempt to delete the media {msg.id} was unsuccessful: {e}")

    try:
        await process.edit_text(AUTO_DEL_SUCCESS_MSG)
    except Exception as e:
        print(f"Could not update the auto-delete notice: {e}")


# ── Caption trimming ────────────────────────────────────────────────────────
# A bot can only send captions of up to 1024 characters. Posts made by a Premium
# account in the DB channel can be up to 2048 characters long, and when the bot
# copies one of those Telegram answers MEDIA_CAPTION_TOO_LONG, so the file never
# reaches the user. shorten_caption() cuts the (HTML) caption at the limit and
# keeps the formatting of the part that is kept valid (open tags get closed).

CAPTION_LIMIT = 1024
_VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "wbr"}


def _utf16_len(text):
    # Telegram counts message length in UTF-16 code units (an emoji can be 2)
    return len(text.encode("utf-16-le")) // 2


class _VisibleLength(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.total = 0

    def handle_data(self, data):
        self.total += _utf16_len(data)


class _Cutter(HTMLParser):
    def __init__(self, budget):
        super().__init__(convert_charrefs=True)
        self.budget = budget
        self.parts = []
        self.open_tags = []
        self.cut = False

    def handle_starttag(self, tag, attrs):
        if self.cut:
            return
        self.parts.append(self.get_starttag_text())
        if tag not in _VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        if not self.cut:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.cut or tag not in self.open_tags:
            return
        while self.open_tags:           # also closes anything left open inside it
            top = self.open_tags.pop()
            self.parts.append("</%s>" % top)
            if top == tag:
                break

    def handle_data(self, data):
        if self.cut:
            return
        used = _utf16_len(data)
        if used <= self.budget:
            self.parts.append(_html_escape(data, quote=False))
            self.budget -= used
            return
        # this piece does not fit completely: keep what fits, then stop
        raw = data.encode("utf-16-le")[: max(self.budget, 0) * 2]
        if raw and 0xD800 <= int.from_bytes(raw[-2:], "little") <= 0xDBFF:
            raw = raw[:-2]              # never leave half of an emoji behind
        kept = raw.decode("utf-16-le").rstrip()
        self.parts.append(_html_escape(kept, quote=False) + "\u2026")
        self.cut = True
        self.budget = 0


def shorten_caption(html_text, limit=CAPTION_LIMIT):
    """Return html_text unchanged when its visible text fits into `limit`
    characters, otherwise a copy cut at the limit and ending with an ellipsis."""
    if not html_text:
        return html_text
    if limit <= 0:
        return ""
    counter = _VisibleLength()
    counter.feed(html_text)
    counter.close()
    if counter.total <= limit:
        return html_text
    cutter = _Cutter(limit - 1)         # one character is kept free for the ellipsis
    cutter.feed(html_text)
    cutter.close()
    while cutter.open_tags:
        cutter.parts.append("</%s>" % cutter.open_tags.pop())
    return "".join(cutter.parts)


subscribed = filters.create(is_subscribed)
