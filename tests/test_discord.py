"""Discord adapter tests with fake message/channel objects. No network."""

import asyncio
from dataclasses import dataclass, field

import pytest

from conftest import OWNER, STRANGER
from human_approved_agents.approval.discord_bot import DiscordApprover, chunk
from human_approved_agents.models import State
from human_approved_agents.voice import Transcriber, VoiceUnavailable

CHANNEL = 1234


@dataclass
class FakeChannel:
    id: int = CHANNEL
    sent: list = field(default_factory=list)

    async def send(self, text, file=None):
        self.sent.append(text)


@dataclass
class FakeAuthor:
    id: str
    bot: bool = False


@dataclass
class FakeAttachment:
    content_type: str = "audio/ogg"

    async def save(self, path):
        path.write_bytes(b"OggS")


@dataclass
class FakeMessage:
    author: FakeAuthor
    content: str
    channel: FakeChannel
    attachments: list = field(default_factory=list)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def bot(orch):
    return DiscordApprover(orch, channel_id=CHANNEL, approvers=frozenset({OWNER}))


def say(approver, user, text, channel=None, is_bot=False):
    ch = channel or FakeChannel()
    run(approver.on_message(FakeMessage(FakeAuthor(user, is_bot), text, ch)))
    return ch.sent


def test_owner_approves_by_user_id(bot, orch):
    assert say(bot, OWNER, "approve 1") == ["Approved #1 v1."]
    assert orch.store.get(1).state is State.APPROVED


def test_stranger_is_refused(bot, orch):
    assert "not on the approver list" in say(bot, STRANGER, "approve 1")[0]
    assert orch.store.get(1).state is State.AWAITING_APPROVAL


def test_bots_and_other_channels_are_ignored(bot, orch):
    assert say(bot, OWNER, "approve 1", is_bot=True) == []
    assert say(bot, OWNER, "approve 1", channel=FakeChannel(id=999)) == []
    assert orch.store.get(1).state is State.AWAITING_APPROVAL


def test_poll_posts_cards_and_delivery_notes(make_orch):
    o = make_orch()
    b = DiscordApprover(o, channel_id=CHANNEL, approvers=frozenset({OWNER}))
    run(b.poll_once())  # no channel yet: nothing happens
    b._channel = FakeChannel()
    run(b.poll_once())
    assert len(b._channel.sent) == 5
    o.handle_command(OWNER, "approve 2")
    run(b.poll_once())
    assert b._channel.sent[-1].startswith("#2 v1: DRY RUN")


class ScriptedTranscriber(Transcriber):
    def __init__(self, text=None, error=False):
        super().__init__("tiny", "cpu", factory=lambda s, d: None)
        self.text, self.error = text, error

    def transcribe(self, audio_path):
        assert audio_path.read_bytes() == b"OggS"
        if self.error:
            raise VoiceUnavailable("no model")
        return self.text


def voice_note(bot, user, transcriber):
    bot.transcriber = transcriber
    ch = FakeChannel()
    run(bot.on_message(FakeMessage(FakeAuthor(user), "", ch, [FakeAttachment()])))
    return ch.sent


def test_voice_note_needs_version(bot, orch):
    sent = voice_note(bot, OWNER, ScriptedTranscriber("Approve number one."))
    assert sent[0] == 'Heard: "approve 1"'
    assert "must say the version" in sent[1]
    sent = voice_note(bot, OWNER, ScriptedTranscriber("Approve one, version one."))
    assert sent[1] == "Approved #1 v1."
    assert orch.store.get(1).state is State.APPROVED


def test_voice_from_stranger_is_not_transcribed(bot):
    t = ScriptedTranscriber("approve one version one")
    assert voice_note(bot, STRANGER, t) == []


def test_voice_off_or_broken(bot):
    ch = FakeChannel()
    run(bot.on_message(FakeMessage(FakeAuthor(OWNER), "", ch, [FakeAttachment()])))
    assert ch.sent == ["Voice is off. Type the command instead."]
    assert voice_note(bot, OWNER, ScriptedTranscriber(error=True)) == [
        "I could not make out that voice note."
    ]


def test_say_queue_without_speaker_sends_text(bot):
    assert say(bot, OWNER, "say queue")[0].startswith("5 items waiting")
    assert say(bot, STRANGER, "say queue") == []  # not a command; strangers get nothing read out


def test_chunk_respects_limit():
    text = "\n".join(["x" * 30] * 10)
    parts = chunk(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(p.replace("\n", "") for p in parts) == "x" * 300
    assert chunk("y" * 250, limit=100) == ["y" * 100, "y" * 100, "y" * 50]
