"""Parse what the human typed (or said) into a command.

Only these change anything:

    approve N            approve the version shown on item N's latest card
    approve N v2         same, but only if v2 is still the current version
    reject N [reason]
    edit N: <new text>   creates a new version that needs its own approval
    lesson: <text>       e.g. lesson: never say "circle back"

Read-only: ``show N``, ``list``, ``help``. Anything else changes nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.IGNORECASE
_APPROVE = re.compile(r"^approve\s+#?(\d+)(?:\s*(?:v|version)\s*(\d+))?\s*[.!]?\s*$", _I)
_REJECT = re.compile(r"^reject\s+#?(\d+)\b\s*[:,-]?\s*(.*)$", _I | re.DOTALL)
_EDIT = re.compile(r"^edit\s+#?(\d+)(?:\s*(?:v|version)\s*(\d+))?\s*:\s*(.+)$", _I | re.DOTALL)
_SHOW = re.compile(r"^show\s+#?(\d+)\s*$", _I)
_LESSON = re.compile(r"^lesson\s*:\s*(.+)$", _I | re.DOTALL)
_APPROVE_ANY = re.compile(r"^approve\b", _I)
_APPROVAL_LIKE = re.compile(
    r"^(yes|yep|ok(ay)?|sure|lgtm|looks good.*|send it.*|ship it.*|go ahead.*|do it.*|"
    r"sounds good.*|approved?\.?|\U0001F44D.*|:\+1:|:thumbsup:)\s*[.!]?$",
    _I,
)


@dataclass(frozen=True)
class Command:
    verb: str  # approve reject edit show list help lesson approval_like ambiguous unknown
    item_id: int | None = None
    version: int | None = None
    text: str = ""


def parse_command(raw: str) -> Command:
    text = raw.strip()
    if m := _APPROVE.match(text):
        return Command("approve", int(m.group(1)), int(m.group(2)) if m.group(2) else None)
    if _APPROVE_ANY.match(text):
        # "approve all", "approve 1 and 2", "approve the roofing one": not one clear item.
        return Command("ambiguous", text=text)
    if m := _REJECT.match(text):
        return Command("reject", int(m.group(1)), text=m.group(2).strip())
    if m := _EDIT.match(text):
        version = int(m.group(2)) if m.group(2) else None
        return Command("edit", int(m.group(1)), version, m.group(3).strip())
    if m := _SHOW.match(text):
        return Command("show", int(m.group(1)))
    if m := _LESSON.match(text):
        return Command("lesson", text=m.group(1).strip())
    if text.lower() in {"list", "queue", "status"}:
        return Command("list")
    if text.lower() in {"help", "?"}:
        return Command("help")
    if _APPROVAL_LIKE.match(text):
        return Command("approval_like", text=text)
    return Command("unknown", text=text)
