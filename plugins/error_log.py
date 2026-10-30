"""Keeps the log readable while Telegram itself is having trouble.

When a handler fails because Telegram cannot answer (its servers are restarting,
a worldwide outage, the network dropped, ...) Pyrofork prints "Unhandled
exception" plus a 40-line traceback for every single update. During an outage
that is hundreds of tracebacks that all say the same thing and hide anything real.

This turns exactly those errors into one short line. Every other error is logged
exactly as Pyrofork would have logged it, traceback included, so real bugs stay
loud.
"""

import logging

from bot import Bot
from config import LOGGER
from telegram_trouble import TELEGRAM_TROUBLE


@Bot.on_error()
async def log_errors(client, update, error):
    if isinstance(error, TELEGRAM_TROUBLE):
        user = getattr(update, "from_user", None)
        LOGGER(__name__).warning(
            "Telegram is having trouble, a handler failed for user %s: %s",
            user.id if user else None,
            str(error) or repr(error),
        )
        return
    logging.getLogger("pyrogram.dispatcher").error("Unhandled exception: %s", error, exc_info=error)
