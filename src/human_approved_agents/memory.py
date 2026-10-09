"""Memory: turn the human's decisions into lessons the Drafter reads next time.

Three kinds of lesson:

* ``edit``   - derived from the difference between the agent's draft and the
               human's edited version ("shortened from 140 to 70 words",
               "removed: 'I hope this finds you well'").
* ``reject`` - the reason given with a rejection.
* ``rule``   - an explicit instruction ("lesson: never say 'circle back'").
               A "never say X" rule also becomes a banned phrase that the
               Reviewer enforces, so it is checked, not just suggested.

Lessons are plain sentences stored in SQLite. They are advice for the LLM
(prompt context), except banned phrases, which are hard rules.
"""

from __future__ import annotations

import re
from datetime import datetime

from .store import Store

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_GREETING = re.compile(
    r"^(hi|hello|hey|dear|thanks|thank you|best|regards|cheers)\b[^.!?]{0,40}[,!]?$", re.I
)
_NEVER_SAY = re.compile(
    r"""^\s*(?:never|don'?t|do\s+not)\s+(?:say|use|write)\s+["'“‘]?(.+?)["'”’]?\s*\.?\s*$""",
    re.IGNORECASE,
)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’$%-]+\b", text))


def sentences(text: str) -> list[str]:
    return [" ".join(s.split()) for s in _SENTENCE.split(text.strip()) if s.strip()]


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9$%']+", text.lower()))


def lessons_from_edit(before: str, after: str, approver: str) -> list[str]:
    """Describe what the human changed, in sentences the Drafter can use."""
    lessons: list[str] = []
    wb, wa = word_count(before), word_count(after)
    if wb and wa <= wb * 0.8:
        lessons.append(f"{approver} shortened a draft from {wb} to {wa} words; aim for about {wa}.")
    elif wa >= wb * 1.25 and wb:
        lessons.append(f"{approver} lengthened a draft from {wb} to {wa} words.")
    # A sentence counts as removed only if its words no longer appear in order
    # anywhere in the new text (so merging two sentences is not a removal).
    # Greetings and sign-offs are ignored.
    after_norm = _norm(after)
    removed = [
        s
        for s in sentences(before)
        if not _GREETING.match(s) and len(s.split()) >= 3 and _norm(s) not in after_norm
    ]
    for s in removed[:3]:
        short = s if len(s) <= 90 else s[:87] + "..."
        lessons.append(f'{approver} removed the sentence: "{short}"')
    return lessons


def parse_never_say(text: str) -> str | None:
    m = _NEVER_SAY.match(text)
    return m.group(1).strip() if m else None


class Memory:
    def __init__(self, store: Store, *, owner_name: str = "The owner", limit: int = 8) -> None:
        self.store = store
        self.owner_name = owner_name
        self.limit = limit

    def record_edit(
        self, *, profile: str, item_id: int, before: str, after: str, now: datetime
    ) -> list[str]:
        new = lessons_from_edit(before, after, self.owner_name)
        for text in new:
            self.store.add_lesson(profile=profile, kind="edit", text=text, now=now, item_id=item_id)
        return new

    def record_rejection(
        self, *, profile: str, item_id: int, reason: str, now: datetime
    ) -> str | None:
        if not reason.strip():
            return None
        text = f"{self.owner_name} rejected a draft because: {reason.strip()}"
        self.store.add_lesson(profile=profile, kind="reject", text=text, now=now, item_id=item_id)
        return text

    def record_rule(self, text: str, now: datetime, profile: str | None = None) -> str | None:
        """Store an explicit rule. Returns the banned phrase if it was a "never say" rule."""
        phrase = parse_never_say(text)
        self.store.add_lesson(
            profile=profile,
            kind="rule",
            text=f"{self.owner_name}'s rule: {text.strip()}",
            now=now,
            banned_phrase=phrase,
        )
        return phrase

    def lessons_for(self, profile: str) -> list[str]:
        rows = self.store.lessons(profile, self.limit)
        return [r["text"] for r in reversed(rows)]

    def banned_phrases(self, profile: str) -> list[str]:
        return self.store.banned_phrases(profile)
