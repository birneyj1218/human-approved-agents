"""Discord approval channel (discord.py).

The bot listens in one channel. It posts each item as a numbered card and
treats messages there as commands. Identity is the Discord user ID of the
author, checked against APPROVER_USER_IDS; display names are never trusted.
Voice notes are transcribed locally when the voice module is enabled.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..orchestrator import Orchestrator
from ..voice import Speaker, Transcriber, VoiceUnavailable, queue_summary, transcript_to_command

log = logging.getLogger(__name__)
DISCORD_LIMIT = 2000


def chunk(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split on line breaks so a card never exceeds Discord's message limit."""
    parts: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) > limit:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return [p.rstrip("\n") for p in parts if p.strip()]


class DiscordApprover:
    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        channel_id: int,
        approvers: frozenset[str],
        poll_seconds: float = 60,
        transcriber: Transcriber | None = None,
        speaker: Speaker | None = None,
    ) -> None:
        self.orch = orchestrator
        self.channel_id = channel_id
        self.approvers = approvers
        self.poll_seconds = poll_seconds
        self.transcriber = transcriber
        self.speaker = speaker
        self._channel: Any = None

    async def post(self, channel: Any, messages: Sequence[str]) -> None:
        for m in messages:
            for part in chunk(m):
                await channel.send(part)

    async def on_message(self, message: Any) -> None:
        if message.author.bot or getattr(message.channel, "id", None) != self.channel_id:
            return
        user_id = str(message.author.id)
        text = (message.content or "").strip()
        source = "text"

        audio = [a for a in message.attachments if (a.content_type or "").startswith("audio/")]
        if not text and audio:
            if self.transcriber is None:
                await message.channel.send("Voice is off. Type the command instead.")
                return
            if user_id not in self.approvers:
                return  # do not spend GPU time on strangers
            text = await self._transcribe(audio[0])
            if not text:
                await message.channel.send("I could not make out that voice note.")
                return
            source = "voice"
            await message.channel.send(f'Heard: "{text}"')

        if text.lower() in {"say queue", "read queue"} and user_id in self.approvers:
            await self._speak_queue(message.channel)
            return

        replies = await asyncio.to_thread(self.orch.handle_command, user_id, text, source=source)
        await self.post(message.channel, replies)

    async def _transcribe(self, attachment: Any) -> str:
        assert self.transcriber is not None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.ogg"
            await attachment.save(path)
            try:
                raw = await asyncio.to_thread(self.transcriber.transcribe, path)
            except VoiceUnavailable as exc:
                log.warning("voice unavailable: %s", exc)
                return ""
        return transcript_to_command(raw)

    async def _speak_queue(self, channel: Any) -> None:
        summary = queue_summary(self.orch.awaiting())
        if self.speaker is None:
            await channel.send(summary)
            return
        import discord

        with tempfile.TemporaryDirectory() as tmp:
            try:
                wav = await asyncio.to_thread(self.speaker.speak, summary, Path(tmp) / "queue.wav")
            except VoiceUnavailable:
                await channel.send(summary)
                return
            await channel.send(summary, file=discord.File(str(wav)))

    async def poll_once(self) -> None:
        if self._channel is None:
            return
        messages = await asyncio.to_thread(self.orch.tick)
        await self.post(self._channel, messages)

    def run(self, token: str) -> None:  # pragma: no cover - needs a live Discord connection
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            self._channel = client.get_channel(self.channel_id)
            if self._channel is None:
                log.error("channel %s not found or bot lacks access", self.channel_id)
                await client.close()
                return
            log.info("approval bot ready")
            while not client.is_closed():
                try:
                    await self.poll_once()
                except Exception:
                    log.exception("poll failed; will retry")
                await asyncio.sleep(self.poll_seconds)

        @client.event
        async def on_message(message: Any) -> None:
            await self.on_message(message)

        client.run(token, log_handler=None)
