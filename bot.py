from aiohttp import web
from plugins import web_server

import pyromod.listen
from pyrogram import Client
import pyrogram.utils as _pyro_utils

# ── New-channel-ID support ──
# Old Pyrogram (2.0.106) caps channel IDs at 32 bits (-1002147483647), so any
# channel created recently (-1003..., -1004... ) fails with "Peer id invalid".
# pyrofork/kurigram already ship the larger limits; this patch only raises the
# limit if the installed library still has the old one.
if _pyro_utils.MIN_CHANNEL_ID > -1007852516352:
    _pyro_utils.MIN_CHANNEL_ID = -1007852516352
if _pyro_utils.MIN_CHAT_ID > -999999999999:
    _pyro_utils.MIN_CHAT_ID = -999999999999
from pyrogram.enums import ParseMode
import asyncio
import signal
import sys
from types import SimpleNamespace
from datetime import datetime

from config import (
    API_HASH, 
    APP_ID, 
    LOGGER, 
    TG_BOT_TOKEN, 
    TG_BOT_WORKERS, 
    FORCE_SUB_CHANNEL, 
    FORCE_SUB_CHANNELS,
    CHANNEL_ID, 
    PORT
)
from keepalive import KeepAliveManager

ascii_art = """
░█████╗░░█████╗░██████╗░███████╗██╗░░██╗██████╗░░█████╗░████████╗███████╗
██╔══██╗██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝██╔══██╗██╔══██╗╚══██╔══╝╚════██║
██║░░╚═╝██║░░██║██║░░██║█████╗░░░╚███╔╝░██████╦╝██║░░██║░░░██║░░░░░███╔═╝
██║░░██╗██║░░██║██║░░██║██╔══╝░░░██╔██╗░██╔══██╗██║░░██║░░░██║░░░██╔══╝░░
╚█████╔╝╚█████╔╝██████╔╝███████╗██╔╝╚██╗██████╦╝╚█████╔╝░░░██║░░░███████╗
░╚════╝░░╚════╝░╚═════╝░╚══════╝╚═╝░░╚═╝╚═════╝░░╚════╝░░░░╚═╝░░░╚══════╝
"""

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="Bot",
            api_hash=API_HASH,
            api_id=APP_ID,
            plugins={"root": "plugins"},
            workers=TG_BOT_WORKERS,
            bot_token=TG_BOT_TOKEN,
        )
        self.LOGGER = LOGGER
        self._keepalive = None

    async def start(self):
        """Setup only. Don't block here — KeepAliveManager handles the run loop."""
        await super().start()

        usr_bot_me = await self.get_me()
        self.uptime = datetime.now()
        self.username = usr_bot_me.username

        # ── Force Sub Channels (1-3, all optional) ──
        self.invitelink = None       # kept for backward compatibility (1st channel)
        self.force_sub_info = {}     # {channel_id: {"link": str, "title": str}}
        for channel_id in FORCE_SUB_CHANNELS:
            try:
                chat = await self.get_chat(channel_id)
                link = chat.invite_link
                if not link:
                    await self.export_chat_invite_link(channel_id)
                    chat = await self.get_chat(channel_id)
                    link = chat.invite_link
                self.force_sub_info[channel_id] = {
                    "link": link,
                    "title": chat.title or "Channel",
                }
                if channel_id == FORCE_SUB_CHANNEL:
                    self.invitelink = link
            except Exception as a:
                self.LOGGER(__name__).warning(a)
                self.LOGGER(__name__).warning(
                    "Bot can't export invite link from Force Sub Channel %s!", channel_id
                )
                self.LOGGER(__name__).warning(
                    "Please double-check the channel ID and ensure bot is admin "
                    "with 'Invite Users via Link' permission. Current: %s",
                    channel_id,
                )
                self.LOGGER(__name__).info(
                    "Bot Stopped. Join https://t.me/CodeXBotzSupport"
                )
                #sys.exit()

        # ── DB Channel ──
        # Never leave self.db_channel unset: every plugin reads db_channel.id.
        # If Telegram can't resolve the channel right now (the bot hasn't
        # "seen" it yet), fall back to the configured ID; Pyrogram caches the
        # peer automatically as soon as any update from the channel arrives
        # (a new post, or the bot being made admin), and later calls work.
        self.db_channel = SimpleNamespace(id=CHANNEL_ID, username=None, title="DB Channel")
        try:
            db_channel = await self.get_chat(CHANNEL_ID)
            self.db_channel = db_channel
            test = await self.send_message(chat_id=db_channel.id, text="Test Message")
            await test.delete()
        except Exception as e:
            self.LOGGER(__name__).warning(e)
            self.LOGGER(__name__).warning(
                "Could not verify DB Channel %s yet. Make sure the bot is Admin there "
                "and post any message in the channel once so the bot can see it. "
                "Continuing with the configured ID.", CHANNEL_ID
            )

        self.set_parse_mode(ParseMode.HTML)
        self.LOGGER(__name__).info("Bot Running..!")
        print(ascii_art)
        print("Welcome to CodeXBotz File Sharing Bot")

        # ── Web server ──
        #app = web.AppRunner(await web_server())
        #await app.setup()
        #await web.TCPSite(app, "0.0.0.0", PORT).start()

        # ── Hand over to keepalive (blocks forever) ──
        self._keepalive = KeepAliveManager(
            client=self,
            heartbeat_interval=60,  # was 5 min — tighter interval means a dead
                                    # connection is caught in under ~2 minutes
                                    # worst-case instead of up to ~5.5 minutes
            reconnect_delay=5,
        )


        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._keepalive.request_shutdown)
            except NotImplementedError:
                pass

        await self._keepalive.run()

        self.LOGGER(__name__).info("Bot stopped.")

    async def stop(self, *args):
        if self._keepalive:
            self._keepalive.request_shutdown()
        if self.is_connected:
            await super().stop()
        self.LOGGER(__name__).info("Bot stopped.")


if __name__ == "__main__":
    bot = Bot()
    try:
        bot.run()
    except KeyboardInterrupt:
        pass
