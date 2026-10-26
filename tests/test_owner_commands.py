"""Owner-only commands should depend on OWNER_ID, not a hardcoded account."""
from plugins import start


class FakeStatusMessage:
    def __init__(self):
        self.edits = []

    async def edit(self, text):
        self.edits.append(text)


class FakeMessage:
    def __init__(self):
        self.reply_to_message = object()
        self.replies = []

    async def reply(self, text, **kwargs):
        status = FakeStatusMessage()
        self.replies.append((text, status))
        return status


async def test_broadcast_runs_for_the_owner(monkeypatch):
    async def full_userbase():
        return []

    monkeypatch.setattr(start, "full_userbase", full_userbase)
    message = FakeMessage()

    await start.send_text(None, message)

    assert message.replies[0][0].startswith("<i>Broadcasting")
    assert "Total Users: <code>0</code>" in message.replies[0][1].edits[-1]
