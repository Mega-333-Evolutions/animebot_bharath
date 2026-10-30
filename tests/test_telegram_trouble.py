"""When Telegram itself is having trouble, /start must still work.

On 26 October 2026 Telegram had a worldwide outage ("-500 No workers running").
The force-sub membership lookup failed inside the `subscribed` filter, then failed
again inside `not_joined`, and the user got no reply at all (and the log got two
40-line tracebacks per attempt).

Now, when Telegram cannot say whether somebody joined, they are let through and get
their files. Anything that is not Telegram being unavailable (a wrong channel ID, a
bug) stays strict and loud.
"""
import asyncio
import logging
from types import SimpleNamespace

import pytest
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    NoWorkersRunning,
    ServiceUnavailable,
    UserIsBlocked,
)
from pyrogram.handlers import ErrorHandler

import helper_func
import telegram_trouble
from plugins import error_log, start
from telegram_trouble import Outage

CHANNEL = -1001234567890
FORCE_CHANNEL = -1009876543210

TROUBLE = [
    NoWorkersRunning(),
    ServiceUnavailable(),
    FloodWait(value=30),
    TimeoutError("Request timed out"),
    ConnectionError("connection reset"),
]

NOT_TROUBLE = [
    KeyError("boom"),
    ChatAdminRequired(),
    ValueError("a bug"),
]


class Clock:
    """A clock the tests move by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeUser:
    id = 12345
    username = "someone"
    first_name = "Some"
    last_name = "One"
    mention = "@someone"


class FakeClient:
    username = "testbot"
    force_sub_info = {FORCE_CHANNEL: {"link": "https://t.me/+invite", "title": "News"}}
    db_channel = SimpleNamespace(id=CHANNEL)


class FakeMessage:
    """Records what the bot answers. `fail_with` makes every answer fail."""

    def __init__(self, text="/start", fail_with=None):
        self.text = text
        self.command = text.lstrip("/").split()
        self.from_user = FakeUser()
        self.replies = []
        self.fail_with = fail_with

    async def reply_text(self, text, **kwargs):
        if self.fail_with:
            raise self.fail_with
        self.replies.append((text, kwargs))
        return SimpleNamespace(deleted=False, delete=self._noop)

    async def reply(self, text, **kwargs):
        return await self.reply_text(text, **kwargs)

    async def _noop(self):
        return None


class Lookup:
    """Stands in for helper_func.subscribed. Each call returns, or raises, the next outcome (the last one repeats)."""

    def __init__(self, *outcomes):
        self.outcomes = outcomes
        self.calls = 0

    async def __call__(self, client, message):
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class Hanging:
    """A lookup that never answers. Records whether it was cancelled."""

    def __init__(self):
        self.calls = 0
        self.cancelled = False

    async def __call__(self, client, message):
        self.calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Every test starts with no outage, a clock it controls, and the default (let people through)."""
    clock = Clock()
    monkeypatch.setattr(start, "outage", Outage(clock=clock))
    monkeypatch.setattr(start, "FORCE_SUB_FAIL_OPEN", True)
    return clock


@pytest.fixture
def clock(fresh_state):
    return fresh_state


@pytest.fixture
def strict(monkeypatch):
    """FORCE_SUB_FAIL_OPEN=0: when Telegram cannot answer, people are asked to try again."""
    monkeypatch.setattr(start, "FORCE_SUB_FAIL_OPEN", False)


def use(monkeypatch, lookup):
    monkeypatch.setattr(start, "subscribed", lookup)
    return lookup


def buttons(markup):
    return [[(b.text, b.url) for b in row] for row in markup.inline_keyboard]


async def ask(message=None):
    return await start._safe_subscribed(None, FakeClient(), message or FakeMessage())


# ── Telegram answers: nothing changes ───────────────────────────────────────


async def test_a_member_passes(monkeypatch):
    lookup = use(monkeypatch, Lookup(True))
    message = FakeMessage()

    assert await ask(message) is True
    assert lookup.calls == 1
    assert not hasattr(message, "_fsub_unavailable")


async def test_a_non_member_is_still_turned_away(monkeypatch):
    use(monkeypatch, Lookup(False))
    message = FakeMessage()

    assert await ask(message) is False
    assert not hasattr(message, "_fsub_unavailable")


async def test_every_user_is_looked_up_while_telegram_works(monkeypatch):
    lookup = use(monkeypatch, Lookup(True, False, True))

    assert [await ask(), await ask(), await ask()] == [True, False, True]
    assert lookup.calls == 3


async def test_nothing_is_logged_while_telegram_works(monkeypatch, caplog):
    use(monkeypatch, Lookup(True))

    with caplog.at_level(logging.INFO):
        await ask()

    assert caplog.records == []


# ── Telegram cannot answer: people are let through ──────────────────────────


@pytest.mark.parametrize("error", TROUBLE, ids=lambda e: type(e).__name__)
async def test_when_telegram_cannot_answer_people_are_let_through(monkeypatch, error):
    use(monkeypatch, Lookup(error))
    message = FakeMessage()

    assert await ask(message) is True
    assert not hasattr(message, "_fsub_unavailable")
    assert start.outage.active()


@pytest.mark.parametrize("error", TROUBLE, ids=lambda e: type(e).__name__)
async def test_an_outage_is_one_quiet_log_line_not_a_traceback(monkeypatch, caplog, error):
    use(monkeypatch, Lookup(error))

    with caplog.at_level(logging.INFO):
        await ask()

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert "12345" in record.getMessage()
    assert "Letting people through" in record.getMessage()


async def test_during_the_outage_nobody_is_looked_up_and_nothing_is_logged(monkeypatch, caplog):
    lookup = use(monkeypatch, Lookup(NoWorkersRunning(), True))
    await ask()

    with caplog.at_level(logging.INFO):
        caplog.clear()
        results = [await ask() for _ in range(5)]

    assert results == [True] * 5
    assert lookup.calls == 1
    assert caplog.records == []


async def test_once_the_window_is_over_the_next_user_is_looked_up_again(monkeypatch, clock):
    lookup = use(monkeypatch, Lookup(NoWorkersRunning(), True))
    await ask()

    clock.advance(telegram_trouble.RECHECK_AFTER - 1)
    await ask()
    assert lookup.calls == 1                        # still inside the window

    clock.advance(2)
    await ask()
    assert lookup.calls == 2                        # window over: asked again


async def test_a_failing_recheck_does_not_repeat_the_warning(monkeypatch, caplog, clock):
    lookup = use(monkeypatch, Lookup(NoWorkersRunning()))
    await ask()
    clock.advance(telegram_trouble.RECHECK_AFTER + 1)

    with caplog.at_level(logging.INFO):
        caplog.clear()
        result = await ask()

    assert result is True
    assert lookup.calls == 2
    assert caplog.records == []                     # same outage: already reported
    assert start.outage.active()                    # and the window starts over


async def test_when_telegram_answers_again_everyone_is_checked_as_usual(monkeypatch, caplog, clock):
    lookup = use(monkeypatch, Lookup(NoWorkersRunning(), False, True))
    assert await ask() is True                      # outage: let through
    clock.advance(telegram_trouble.RECHECK_AFTER + 1)

    with caplog.at_level(logging.INFO):
        caplog.clear()
        assert await ask() is False                 # Telegram is back: a non-member is turned away again
    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert "answers again" in caplog.records[0].getMessage()

    assert not start.outage.active()
    assert await ask() is True                      # and the window is gone: this user was looked up too
    assert lookup.calls == 3


async def test_a_new_outage_after_a_recovery_is_reported_again(monkeypatch, caplog, clock):
    use(monkeypatch, Lookup(NoWorkersRunning(), True, NoWorkersRunning()))
    await ask()
    clock.advance(telegram_trouble.RECHECK_AFTER + 1)
    await ask()                                     # recovered

    with caplog.at_level(logging.WARNING):
        caplog.clear()
        await ask()                                 # down again

    assert [r.levelno for r in caplog.records] == [logging.WARNING]


async def test_a_lookup_that_hangs_is_cut_off_and_the_user_is_let_through(monkeypatch, caplog):
    hanging = use(monkeypatch, Hanging())
    monkeypatch.setattr(start, "CHECK_TIMEOUT", 0.05)
    message = FakeMessage()

    with caplog.at_level(logging.WARNING):
        result = await asyncio.wait_for(ask(message), timeout=5)

    assert result is True
    assert hanging.cancelled is True                # the stuck lookup does not keep a worker busy
    assert not hasattr(message, "_fsub_unavailable")
    assert start.outage.active()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


async def test_the_real_timeout_is_short_enough_to_matter():
    assert 0 < telegram_trouble.CHECK_TIMEOUT <= 15
    assert 0 < telegram_trouble.RECHECK_AFTER <= 120


async def test_a_user_with_a_file_link_gets_the_files_during_an_outage(monkeypatch, caplog):
    """The whole point: Telegram cannot verify them, so they are let through and served."""
    use(monkeypatch, Lookup(NoWorkersRunning()))
    delivered = []

    async def add_user(user_id, username=None):
        return None

    async def get_messages(client, ids):
        return [SimpleNamespace(id=i, document=None, caption=None, reply_markup=None) for i in ids]

    async def copy_to_user(msg, user_id, caption, reply_markup):
        delivered.append(msg.id)
        return SimpleNamespace(id=1000 + msg.id)

    monkeypatch.setattr(start, "add_user", add_user)
    monkeypatch.setattr(start, "get_messages", get_messages)
    monkeypatch.setattr(start, "copy_to_user", copy_to_user)
    monkeypatch.setattr(start, "AUTO_DELETE_TIME", 0)
    payload = await helper_func.encode(f"get-{7 * abs(CHANNEL)}-{9 * abs(CHANNEL)}")
    message = FakeMessage(f"/start {payload}")

    assert await ask(message) is True               # what the dispatcher asks first
    await start.start_command(FakeClient(), message)  # then it runs the /start handler

    assert delivered == [7, 8, 9]
    assert [text for text, _ in message.replies] == ["Please wait..."]


# ── anything that is not Telegram being unavailable stays strict and loud ───


@pytest.mark.parametrize("error", NOT_TROUBLE, ids=lambda e: type(e).__name__)
async def test_a_real_error_is_not_an_outage_and_nobody_is_let_through(monkeypatch, caplog, error):
    lookup = use(monkeypatch, Lookup(error))
    message = FakeMessage()

    with caplog.at_level(logging.WARNING):
        result = await ask(message)

    assert result is False
    assert message._fsub_unavailable is True
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
    assert caplog.records[0].exc_info is not None   # the traceback is kept: this one needs fixing
    assert not start.outage.active()

    await ask()
    assert lookup.calls == 2                        # the next user is looked up, not waved through


# ── FORCE_SUB_FAIL_OPEN=0: strict ───────────────────────────────────────────


@pytest.mark.parametrize("error", TROUBLE, ids=lambda e: type(e).__name__)
async def test_strict_mode_turns_people_away_when_telegram_cannot_answer(monkeypatch, caplog, strict, error):
    use(monkeypatch, Lookup(error))
    message = FakeMessage()

    with caplog.at_level(logging.WARNING):
        result = await ask(message)

    assert result is False
    assert message._fsub_unavailable is True
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert caplog.records[0].exc_info is None


async def test_strict_mode_has_no_window_everybody_is_looked_up(monkeypatch, strict):
    lookup = use(monkeypatch, Lookup(NoWorkersRunning()))

    assert [await ask(), await ask(), await ask()] == [False, False, False]
    assert lookup.calls == 3
    assert not start.outage.active()


async def test_strict_mode_also_cuts_off_a_lookup_that_hangs(monkeypatch, strict):
    hanging = use(monkeypatch, Hanging())
    monkeypatch.setattr(start, "CHECK_TIMEOUT", 0.05)
    message = FakeMessage()

    assert await asyncio.wait_for(ask(message), timeout=5) is False
    assert hanging.cancelled is True
    assert message._fsub_unavailable is True


def test_the_switch_reads_the_environment(monkeypatch):
    for value, expected in (("0", False), ("false", False), ("OFF", False), (" no ", False), ("1", True), ("", True), ("yes", True)):
        monkeypatch.setenv("FORCE_SUB_FAIL_OPEN", value)
        assert telegram_trouble.env_flag("FORCE_SUB_FAIL_OPEN") is expected, value
    monkeypatch.delenv("FORCE_SUB_FAIL_OPEN")
    assert telegram_trouble.env_flag("FORCE_SUB_FAIL_OPEN") is True      # the default is: let people through


# ── the Outage bookkeeping ──────────────────────────────────────────────────


def test_a_fresh_outage_tracker_is_quiet():
    outage = Outage(clock=Clock())

    assert not outage.active()
    assert outage.ok() is False                    # nothing to recover from


def test_the_window_lasts_exactly_as_long_as_asked():
    clock = Clock()
    outage = Outage(clock=clock)

    assert outage.start(30) is True
    clock.advance(29.9)
    assert outage.active()
    clock.advance(0.2)
    assert not outage.active()


def test_only_the_first_failure_of_an_outage_counts_as_new():
    outage = Outage(clock=Clock())

    assert outage.start(30) is True
    assert outage.start(30) is False
    assert outage.ok() is True                     # ends it...
    assert outage.start(30) is True                # ...so the next one is new again


def test_a_success_closes_the_window_at_once():
    clock = Clock()
    outage = Outage(clock=clock)
    outage.start(30)

    outage.ok()

    assert not outage.active()


# ── not_joined ──────────────────────────────────────────────────────────────


async def test_not_joined_does_not_ask_telegram_a_second_time(monkeypatch):
    lookups = []

    async def lookup(client, user_id):
        lookups.append(user_id)
        raise NoWorkersRunning()

    monkeypatch.setattr(start, "get_missing_fsub_channels", lookup)
    message = FakeMessage()
    message._fsub_unavailable = True

    await start.not_joined(FakeClient(), message)

    assert lookups == [], "the lookup that just failed in the filter must not be repeated"
    assert len(message.replies) == 1
    text, kwargs = message.replies[0]
    assert "can't check whether you have joined" in text
    assert buttons(kwargs["reply_markup"]) == [[("Try Again", "https://t.me/testbot?start=start")]]


async def test_try_again_reopens_the_same_file_link(monkeypatch):
    async def lookup(client, user_id):
        raise NoWorkersRunning()

    monkeypatch.setattr(start, "get_missing_fsub_channels", lookup)
    message = FakeMessage("/start Z2V0LTEyMw")

    await start.not_joined(FakeClient(), message)

    assert buttons(message.replies[0][1]["reply_markup"]) == [[("Try Again", "https://t.me/testbot?start=Z2V0LTEyMw")]]


@pytest.mark.parametrize("error", TROUBLE, ids=lambda e: type(e).__name__)
async def test_not_joined_survives_telegram_failing_between_filter_and_handler(monkeypatch, caplog, error):
    async def lookup(client, user_id):
        raise error

    monkeypatch.setattr(start, "get_missing_fsub_channels", lookup)
    message = FakeMessage()

    with caplog.at_level(logging.WARNING):
        await start.not_joined(FakeClient(), message)

    assert len(message.replies) == 1
    assert "can't check whether you have joined" in message.replies[0][0]
    assert all(record.exc_info is None for record in caplog.records)


async def test_not_joined_still_shows_the_join_buttons_when_telegram_answers(monkeypatch):
    async def missing(client, user_id):
        return [FORCE_CHANNEL]

    monkeypatch.setattr(start, "get_missing_fsub_channels", missing)
    monkeypatch.setattr(start, "FORCE_SUB_CHANNELS", [FORCE_CHANNEL])
    message = FakeMessage()

    await start.not_joined(FakeClient(), message)

    assert len(message.replies) == 1
    rows = buttons(message.replies[0][1]["reply_markup"])
    assert rows == [[("Join News Channel", "https://t.me/+invite")], [("Try Again", "https://t.me/testbot?start=start")]]
    assert "can't check" not in message.replies[0][0]


def test_the_notices_do_not_blame_telegram():
    """They also show for errors that are not Telegram's fault, so they must not claim a cause."""
    assert "Telegram" not in start.FSUB_UNAVAILABLE_MSG
    assert "Telegram" not in start.FILES_FAILED_MSG


# ── the notice itself ───────────────────────────────────────────────────────


async def test_a_notice_that_cannot_be_sent_is_not_a_traceback(caplog):
    message = FakeMessage(fail_with=NoWorkersRunning())

    with caplog.at_level(logging.WARNING):
        await start.notify(message, "hello")

    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is None


async def test_a_user_who_blocked_the_bot_is_left_alone(caplog):
    message = FakeMessage(fail_with=UserIsBlocked())

    with caplog.at_level(logging.WARNING):
        await start.notify(message, "hello")

    assert caplog.records == []


# ── delivering files ────────────────────────────────────────────────────────


@pytest.fixture
def file_link(monkeypatch):
    """/start <link to DB-channel posts 7, 8 and 9>, with Telegram and the database faked."""

    async def add_user(user_id, username=None):
        return None

    async def get_messages(client, ids):
        return [SimpleNamespace(id=i, document=None, caption=None, reply_markup=None) for i in ids]

    monkeypatch.setattr(start, "add_user", add_user)
    monkeypatch.setattr(start, "get_messages", get_messages)
    monkeypatch.setattr(start, "AUTO_DELETE_TIME", 0)

    async def make(first=7, last=9):
        payload = await helper_func.encode(f"get-{first * abs(CHANNEL)}-{last * abs(CHANNEL)}")
        return FakeMessage(f"/start {payload}")

    return make


def delivery(monkeypatch, fail_ids=(), error=None):
    """Replace the copy step; the posts in `fail_ids` fail with `error`. Returns the list of delivered ids."""
    delivered = []

    async def copy_to_user(msg, user_id, caption, reply_markup):
        if msg.id in fail_ids:
            raise error or NoWorkersRunning()
        delivered.append(msg.id)
        return SimpleNamespace(id=1000 + msg.id)

    monkeypatch.setattr(start, "copy_to_user", copy_to_user)
    return delivered


async def test_all_files_arrive_and_nothing_extra_is_said(monkeypatch, file_link):
    delivered = delivery(monkeypatch)
    message = await file_link()

    await start.start_command(FakeClient(), message)

    assert delivered == [7, 8, 9]
    assert [text for text, _ in message.replies] == ["Please wait..."]


async def test_a_file_that_fails_is_reported_and_the_others_still_arrive(monkeypatch, file_link):
    delivered = delivery(monkeypatch, fail_ids={8})
    message = await file_link()

    await start.start_command(FakeClient(), message)

    assert delivered == [7, 9]
    notice, kwargs = message.replies[-1]
    assert "1 file could not be sent" in notice
    assert buttons(kwargs["reply_markup"])[0][0][0] == "Try Again"


async def test_when_every_file_fails_the_user_is_told_once(monkeypatch, file_link):
    delivered = delivery(monkeypatch, fail_ids={7, 8, 9})
    message = await file_link()

    await start.start_command(FakeClient(), message)

    assert delivered == []
    notices = [text for text, _ in message.replies if "could not be sent" in text]
    assert len(notices) == 1
    assert "3 files could not be sent" in notices[0]


async def test_a_flood_wait_that_fails_again_is_reported_too(monkeypatch, file_link):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(start.asyncio, "sleep", no_sleep)
    delivered = delivery(monkeypatch, fail_ids={8}, error=FloodWait(value=30))
    message = await file_link()

    await start.start_command(FakeClient(), message)

    assert delivered == [7, 9]
    assert "1 file could not be sent" in message.replies[-1][0]


async def test_the_log_names_the_file_that_failed(monkeypatch, file_link, caplog):
    delivery(monkeypatch, fail_ids={8})
    message = await file_link()

    with caplog.at_level(logging.WARNING):
        await start.start_command(FakeClient(), message)

    assert any("message 8" in record.getMessage() and "12345" in record.getMessage() for record in caplog.records)


async def test_a_blocked_user_is_not_told_anything(monkeypatch, file_link):
    delivered = delivery(monkeypatch, fail_ids={8}, error=UserIsBlocked())
    message = await file_link()

    await start.start_command(FakeClient(), message)

    assert delivered == [7]
    assert not any("could not be sent" in text for text, _ in message.replies)


async def test_a_failing_please_wait_message_does_not_stop_the_files(monkeypatch, file_link):
    delivered = delivery(monkeypatch)
    message = await file_link()
    real_reply = message.reply_text
    calls = {"n": 0}

    async def reply_text(text, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:                      # the "Please wait..." message
            raise NoWorkersRunning()
        return await real_reply(text, **kwargs)

    message.reply_text = reply_text

    await start.start_command(FakeClient(), message)

    assert delivered == [7, 8, 9]


async def test_a_leftover_please_wait_message_does_not_stop_the_files(monkeypatch, file_link):
    delivered = delivery(monkeypatch)
    message = await file_link()

    async def reply_text(text, **kwargs):
        async def cannot_delete():
            raise NoWorkersRunning()

        return SimpleNamespace(delete=cannot_delete)

    message.reply = reply_text

    await start.start_command(FakeClient(), message)

    assert delivered == [7, 8, 9]


# ── the log filter for everything else ──────────────────────────────────────


def test_the_error_handler_is_registered_with_pyrofork():
    handlers = error_log.log_errors.handlers

    assert len(handlers) == 1
    handler, group = handlers[0]
    assert isinstance(handler, ErrorHandler)
    assert group == 0


@pytest.mark.parametrize("error", TROUBLE, ids=lambda e: type(e).__name__)
async def test_telegram_trouble_in_any_handler_is_one_quiet_line(caplog, error):
    update = SimpleNamespace(from_user=FakeUser())

    with caplog.at_level(logging.WARNING):
        await error_log.log_errors(None, update, error)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is None
    assert "12345" in caplog.records[0].getMessage()


async def test_any_other_error_is_still_logged_with_its_traceback(caplog):
    try:
        raise ValueError("a real bug")
    except ValueError as error:
        caught = error

    with caplog.at_level(logging.WARNING):
        await error_log.log_errors(None, SimpleNamespace(from_user=FakeUser()), caught)

    assert len(caplog.records) == 1
    assert caplog.records[0].name == "pyrogram.dispatcher"
    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.records[0].exc_info[1] is caught


async def test_an_update_without_a_user_does_not_break_the_handler(caplog):
    with caplog.at_level(logging.WARNING):
        await error_log.log_errors(None, SimpleNamespace(), NoWorkersRunning())

    assert len(caplog.records) == 1
