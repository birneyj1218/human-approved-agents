"""Outbound delivery. Dry-run by default.

``Delivery`` is the only code path that calls a ``Sender``. It refuses to
send unless the item was approved, the text matches the approved hash
byte-for-byte, SEND_ENABLED is true, and the hourly send limit allows it.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from .clock import Clock, utcnow
from .models import Item, Lead, State, content_hash
from .ratelimit import SlidingWindowLimiter


class Sender(Protocol):
    name: str

    def send(self, lead: Lead, text: str) -> str:
        """Deliver ``text`` as a reply to ``lead``. Return a receipt string."""
        ...


class ConsoleSender:
    name = "console"

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout

    def send(self, lead: Lead, text: str) -> str:
        self.stream.write(f"--- SENT to {lead.reply_to or lead.contact_name} ---\n{text}\n")
        return f"console:{lead.source_id}"


class FileSender:
    """Appends each message to a JSONL outbox; something else can pick it up."""

    name = "file"

    def __init__(self, path: Path, clock: Clock = utcnow) -> None:
        self.path = path
        self.clock = clock
        path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, lead: Lead, text: str) -> str:
        record = {
            "at": self.clock().isoformat(),
            "profile": lead.profile,
            "to": lead.reply_to,
            "in_reply_to": lead.source_id,
            "text": text,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return f"file:{self.path.name}"


class DeliveryRefused(Exception):
    pass


class RateLimited(Exception):
    pass


@dataclass(frozen=True)
class DeliveryResult:
    mode: str  # "dry_run" | "sent"
    receipt: str
    text: str


class Delivery:
    def __init__(
        self, sender: Sender, *, send_enabled: bool, limiter: SlidingWindowLimiter
    ) -> None:
        self.sender = sender
        self.send_enabled = send_enabled
        self.limiter = limiter

    def deliver(self, item: Item) -> DeliveryResult:
        if item.state is not State.APPROVED or item.approved_version is None:
            raise DeliveryRefused(f"item {item.id} is not approved")
        version = next((v for v in item.versions if v.number == item.approved_version), None)
        if version is None or content_hash(version.text) != item.approved_hash:
            raise DeliveryRefused(f"item {item.id}: text does not match what was approved")
        if not self.send_enabled:
            return DeliveryResult(
                "dry_run", f"dry-run: would send via {self.sender.name}", version.text
            )
        if not self.limiter.allow("send"):
            raise RateLimited("hourly send limit reached; will retry")
        return DeliveryResult("sent", self.sender.send(item.lead, version.text), version.text)
