"""What to do when Telegram itself cannot answer.

TELEGRAM_TROUBLE lists the errors that mean "Telegram cannot answer right now":
its servers restarting or down for everybody (-500 "No workers running", 503), the
network dropping, or a flood wait too long to simply sleep through. They say
nothing about the request being wrong. OSError also covers ConnectionError and
TimeoutError.

When that happens to the force-sub membership lookup, people are let through
(FORCE_SUB_FAIL_OPEN). Set FORCE_SUB_FAIL_OPEN=0 to be strict instead: then they
are asked to try again later.
"""

import asyncio
import os
import time

from pyrogram.errors import FloodWait, InternalServerError, ServiceUnavailable

# asyncio.TimeoutError is the same class as TimeoutError (an OSError) on Python 3.11, but not on older versions.
TELEGRAM_TROUBLE = (InternalServerError, ServiceUnavailable, FloodWait, OSError, asyncio.TimeoutError)


def env_flag(name, default=True):
    """An on/off setting from the environment: 0, false, no or off mean off, anything else on."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


FORCE_SUB_FAIL_OPEN = env_flag("FORCE_SUB_FAIL_OPEN")

# A membership lookup that takes longer than this (seconds) counts as "Telegram cannot answer".
# Normally it takes a fraction of a second; Pyrofork's own retries can add up to a minute.
CHECK_TIMEOUT = 10.0

# After a lookup failed, nobody is looked up for this long (seconds): they are let
# through at once instead of each waiting for the same failure.
RECHECK_AFTER = 30.0


class Outage:
    """Remembers, for a short while, that Telegram could not answer the membership lookup."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._until = 0.0
        self.down = False

    def start(self, seconds):
        """A lookup just failed. Returns True when this is the first failure of a new outage."""
        first = not self.down
        self.down = True
        self._until = self._clock() + seconds
        return first

    def active(self):
        """True while lookups are being skipped."""
        return self._clock() < self._until

    def ok(self):
        """A lookup just worked. Returns True when that ends an outage."""
        was_down = self.down
        self.down = False
        self._until = 0.0
        return was_down


outage = Outage()
