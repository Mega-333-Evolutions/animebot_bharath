from aiohttp import web
from plugins import web_server

import pyromod.listen
from pyrogram import Client
from pyrogram.enums import ParseMode
import asyncio
import signal
import sys
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
        try:
            db_channel = await self.get_chat(CHANNEL_ID)
            if not db_channel:
                db_channel - await self.get_chat("gunsncoffee")
            self.db_channel = db_channel
            test = await self.send_message(chat_id=db_channel.id, text="Test Message")
            await test.delete()
        except Exception as e:
            self.LOGGER(__name__).warning(e)
            self.LOGGER(__name__).warning(
                "Make sure bot is Admin in DB Channel. Double-check CHANNEL_ID. "
                "Current: %s", CHANNEL_ID
            )
            self.LOGGER(__name__).info(
                "Bot Stopped. Join https://t.me/CodeXBotzSupport"
            )
            #sys.exit()

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
