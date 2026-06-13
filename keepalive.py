import asyncio
import logging
from datetime import datetime

from pyrogram import Client, idle, raw
from pyrogram.raw import types

logger = logging.getLogger("KeepAlive")


class KeepAliveManager:
    """
    Wraps a Pyrogram Client to provide:
    1. Heartbeat keep-alive (prevents idle TCP timeout)
    2. Auto-reconnect on disconnect/crash
    3. UpdatesTooLong detection and recovery
    """

    def __init__(
        self,
        client: Client,
        heartbeat_interval: int = 300,      # 5 minutes
        reconnect_delay: int = 5,           # seconds between reconnect attempts
        heartbeat_timeout: int = 30,        # seconds to wait for get_me()
    ):
        self.client = client
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_delay = reconnect_delay
        self.heartbeat_timeout = heartbeat_timeout

        self._heartbeat_task: asyncio.Task | None = None
        self._updates_too_long_flag = asyncio.Event()
        self._shutdown_flag = asyncio.Event()
        self._is_running = False

    # ── Public API ──────────────────────────────────────────────

    async def run(self):
        """
        Blocking entry point. Starts the client, keep-alive, and raw update
        handler, then monitors health. Automatically reconnects on failure.
        """
        self._is_running = True

        while self._is_running:
            try:
                await self._lifecycle()
            except Exception as exc:
                logger.exception("Lifecycle crashed: %s", exc)

            if self._shutdown_flag.is_set():
                logger.info("Shutdown requested, exiting run loop.")
                break

            logger.info("Reconnecting in %d seconds...", self.reconnect_delay)
            await asyncio.sleep(self.reconnect_delay)

    def request_shutdown(self):
        """Signal the manager to stop and not reconnect."""
        self._shutdown_flag.set()
        self._updates_too_long_flag.set()  # unblock any waiting coros

    # ── Internal lifecycle ──────────────────────────────────────

    async def _lifecycle(self):
        """One full start → run → stop cycle."""
        # Clear the flag before starting so a leftover set from the previous
        # cycle doesn't cause _wait_for_failure to return immediately, which
        # would trigger client.start() on an already-running client.
        self._updates_too_long_flag.clear()

        if self.client.is_connected:
            logger.info("Client already running — reusing existing connection.")
        else:
            await self.client.start()

        # Register raw update handler to catch UpdatesTooLong
        self.client.add_handler(
            raw.handlers.RawUpdateHandler(self._raw_update_handler),
            group=-1,  # highest priority
        )

        # Start heartbeat in background
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Wait until something breaks or we're told to stop
        try:
            await self._wait_for_failure()
        finally:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

            try:
                await self.client.stop()
            except Exception as exc:
                logger.warning("Error during client.stop(): %s — forcing disconnect", exc)
                try:
                    await self.client.disconnect()
                except Exception as exc2:
                    logger.warning("Error during forced disconnect: %s", exc2)

    async def _wait_for_failure(self):
        """
        Blocks until one of:
        - idle() returns (connection lost)
        - UpdatesTooLong is detected
        - shutdown is requested
        """
        idle_task = asyncio.create_task(idle())
        too_long_task = asyncio.create_task(self._updates_too_long_flag.wait())
        shutdown_task = asyncio.create_task(self._shutdown_flag.wait())

        done, pending = await asyncio.wait(
            [idle_task, too_long_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        if too_long_task in done:
            logger.warning("UpdatesTooLong triggered — forcing reconnect.")
            self._updates_too_long_flag.clear()

    # ── Heartbeat ───────────────────────────────────────────────

    async def _heartbeat_loop(self):
        """Periodically pings Telegram to keep the TCP connection alive."""
        while True:
            try:
                await asyncio.wait_for(
                    self.client.get_me(),
                    timeout=self.heartbeat_timeout,
                )
                logger.debug("Heartbeat OK at %s", datetime.now().isoformat())
            except asyncio.TimeoutError:
                logger.warning("Heartbeat timed out — connection likely stale.")
                # Let the main loop detect the failure and reconnect
                return
            except Exception as exc:
                logger.warning("Heartbeat failed: %s", exc)
                return

            try:
                await asyncio.wait_for(
                    self._shutdown_flag.wait(),
                    timeout=self.heartbeat_interval,
                )
                return  # shutdown requested
            except asyncio.TimeoutError:
                pass  # normal interval elapsed, loop again

    # ── Raw Update Handler ──────────────────────────────────────

    async def _raw_update_handler(self, client, update, users, chats):
        """
        Pyrogram RawUpdateHandler callback.
        If Telegram sends UpdatesTooLong, we flag it so the main loop reconnects.
        """
        if isinstance(update, types.UpdatesTooLong):
            logger.warning("Received UpdatesTooLong from Telegram.")
            self._updates_too_long_flag.set()

        # Pass through (don't consume the update)
        raise raw.handlers.ContinuePropagation
