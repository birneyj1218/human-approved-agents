"""Plain data types shared by every component."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class State(StrEnum):
    NEW = "new"
    DRAFTED = "drafted"
    REVIEWED = "reviewed"
    AWAITING_APPROVAL = "awaiting_approval"
    EDITED = "edited"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


@dataclass(frozen=True)
class Lead:
    """One piece of input found by the Researcher (a job post, a customer email...)."""

    profile: str
    source_id: str
    title: str
    body: str
    contact_name: str = ""
    reply_to: str = ""


@dataclass(frozen=True)
class Issue:
    rule: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class Review:
    issues: tuple[Issue, ...] = ()
    word_count: int = 0

    @property
    def passed(self) -> bool:
        return not any(i.blocking for i in self.issues)


@dataclass(frozen=True)
class Version:
    number: int
    text: str
    author: str  # "drafter" or "human:<user id>"
    created_at: datetime
    review: Review | None = None

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)


@dataclass
class Item:
    id: int
    lead: Lead
    state: State
    created_at: datetime
    versions: list[Version] = field(default_factory=list)
    redrafts: int = 0
    approved_version: int | None = None
    approved_hash: str | None = None
    approved_by: str | None = None

    @property
    def current(self) -> Version | None:
        return self.versions[-1] if self.versions else None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
