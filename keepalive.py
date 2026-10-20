"""
Last-resort watchdog for the bot.

What it does
------------
Pyrofork already reconnects to Telegram by itself (it pings every 5 seconds and
restarts its session when the socket goes quiet), so this module never tries to
"reconnect" anything and never stops the client.

It only answers one question: has the bot been able to talk to Telegram recently?

  * every WATCHDOG_INTERVAL seconds a tiny MTProto Ping is sent; any answer from
    Telegram (even an error) counts as "alive"
  * a separate daemon thread watches the time of the last answer
  * if there has been no answer for WATCHDOG_STALE_AFTER seconds, the library
    failed to heal itself (a wedged connection) -> the process restarts itself:
    it exits with code 1 and entrypoint.sh starts a fresh one a few seconds later
    (or, when the bot was not started through entrypoint.sh, it re-launches itself
    in place, so it never depends on the Dockerfile)

Short Telegram-side hiccups (slow API calls, "No workers running", flood waits,
a few seconds without network) never trigger a restart: only a Telegram that has
not answered at all for minutes does.

Settings (environment variables, all optional)
----------------------------------------------
  WATCHDOG_INTERVAL     seconds between pings                   default 20
  WATCHDOG_TIMEOUT      seconds to wait for one ping            default 15
  WATCHDOG_STALE_AFTER  silence (seconds) before restarting     default 120
                        set to 0 to switch the watchdog off
"""
import asyncio
import faulthandler
import logging
import os
import random
import sys
import threading
import time

from pyrogram import raw
from pyrogram.errors import RPCError

logger = logging.getLogger("Watchdog")


def _setting(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


class Watchdog:
    def __init__(self, client, interval=None, probe_timeout=None, stale_after=None,
                 check_every=None, exit_code=1):
        self.client = client
        self.interval = interval if interval is not None else _setting("WATCHDOG_INTERVAL", 20)
        self.probe_timeout = probe_timeout if probe_timeout is not None else _setting("WATCHDOG_TIMEOUT", 15)
        self.stale_after = stale_after if stale_after is not None else _setting("WATCHDOG_STALE_AFTER", 120)
        self.check_every = check_every if check_every is not None else max(0.2, min(10.0, self.stale_after / 6))
        self.exit_code = exit_code

        self._last_ok = time.monotonic()
        self._silent_since = None        # start of the current run of failed pings
        self._last_report = time.monotonic()
        self._last_unexpected = float("-inf")
        self._task = None
        self._thread = None
        self._stopping = threading.Event()

    # ── public API ──────────────────────────────────────────────

    def start(self):
        """Arm the watchdog. Must be called from inside the running event loop."""
        if self.stale_after <= 0:
            logger.info("Watchdog is switched off (WATCHDOG_STALE_AFTER=0).")
            return
        self._last_ok = time.monotonic()
        self._last_report = self._last_ok
        self._stopping.clear()
        self._task = asyncio.get_running_loop().create_task(self._probe_loop())
        self._thread = threading.Thread(target=self._monitor, name="watchdog-monitor", daemon=True)
        self._thread.start()
        logger.info(
            "Watchdog armed: Telegram ping every %.0fs, the process restarts itself "
            "if Telegram stays silent for %.0fs.", self.interval, self.stale_after,
        )

    def stop(self):
        """Disarm (called on a normal shutdown so it can never fire while stopping)."""
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()

    # ── ping side (runs on the bot's event loop) ───────────────

    async def _probe_loop(self):
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self._probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # a bug in the probe must never take the bot down or kill this loop
                logger.exception("Watchdog: unexpected error while pinging (ignored).")

    async def _probe_once(self):
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                self.client.invoke(
                    raw.functions.Ping(ping_id=random.getrandbits(62)),
                    retries=0,
                    timeout=self.probe_timeout,
                ),
                timeout=self.probe_timeout + 20,
            )
        except RPCError:
            pass  # Telegram answered with an error -> the connection is alive
        except (asyncio.TimeoutError, OSError) as exc:
            # TimeoutError and ConnectionError are OSError subclasses
            self._record_silence(exc)
            return
        except Exception:
            # Not a network symptom, so most likely a problem in this probe itself.
            # That must never be able to restart a healthy bot.
            now = time.monotonic()
            if now - self._last_unexpected >= 3600:
                self._last_unexpected = now
                logger.exception("Watchdog: unexpected error while pinging (treated as alive).")
        self._record_answer(time.monotonic() - started)

    def _record_answer(self, round_trip):
        now = time.monotonic()
        if self._silent_since is not None:
            logger.warning("Watchdog: Telegram is answering again after %.0fs of silence.",
                           now - self._silent_since)
            self._silent_since = None
        self._last_ok = now
        if now - self._last_report >= 3600:
            self._last_report = now
            logger.info("Watchdog: connection healthy (ping round-trip %.0f ms).", round_trip * 1000)

    def _record_silence(self, exc):
        if self._silent_since is None:
            self._silent_since = time.monotonic()
            logger.warning(
                "Watchdog: no answer from Telegram (%s). The process will restart itself "
                "if this lasts %.0fs.", type(exc).__name__, self.stale_after,
            )

    # ── monitor side (plain thread, works even if the event loop is stuck) ──

    def _monitor(self):
        strikes = 0
        while not self._stopping.wait(self.check_every):
            if time.monotonic() - self._last_ok < self.stale_after:
                strikes = 0
                continue
            # Silent for too long. Look once more before pulling the plug, so a process
            # that was merely frozen for a while gets a chance to ping again first.
            strikes += 1
            if strikes >= 2:
                self._die(time.monotonic() - self._last_ok)
                return

    def _die(self, silent_for):
        supervised = os.environ.get("BOT_SUPERVISED") == "1"   # exported by entrypoint.sh
        # fail-safe: even if logging itself is blocked, the process still goes away
        failsafe = threading.Timer(5.0, os._exit, args=(self.exit_code,))
        failsafe.daemon = True
        failsafe.start()
        try:
            logger.critical(
                "Watchdog: no answer from Telegram for %.0fs (limit %.0fs). %s",
                silent_for, self.stale_after,
                "Exiting so entrypoint.sh can start a fresh process." if supervised
                else "Restarting the process in place.",
            )
        except Exception:
            pass
        try:
            # shows where every thread was stuck, so a wedge can be diagnosed afterwards
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        except Exception:
            pass
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        for handler in list(logging.getLogger().handlers):
            try:
                handler.flush()
            except Exception:
                pass
        if not supervised:
            try:
                exe = sys.executable
                orig = getattr(sys, "orig_argv", None)           # Python 3.10+
                args = [exe] + (list(orig[1:]) if orig else list(sys.argv))
                os.execv(exe, args)                              # replaces this process
            except Exception:
                pass                                             # fall through to a plain exit
        os._exit(self.exit_code)
