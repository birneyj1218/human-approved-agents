"""Turn a voice transcript into the same text command a person would type."""

from __future__ import annotations

import re

_UNITS = {
    # No homophones ("to", "for"): a guessed number should fail, not match.
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_FILLER = {"number", "item", "please", "um", "uh", "the", "okay", "ok"}


def _words_to_numbers(words: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in _TENS:
            n = _TENS[w]
            if i + 1 < len(words) and words[i + 1] in _UNITS and _UNITS[words[i + 1]] < 10:
                n += _UNITS[words[i + 1]]
                i += 1
            out.append(str(n))
        elif w in _UNITS:
            out.append(str(_UNITS[w]))
        else:
            out.append(w)
        i += 1
    return out


def transcript_to_command(transcript: str) -> str:
    """'Approve number three, version two.' -> 'approve 3 v2'.

    Only approve/reject/show/list are mapped. Edits by voice are not
    supported: dictated text is too easy to mangle for something that gets sent.
    """
    words = re.findall(r"[a-z0-9]+", transcript.lower())
    words = [w for w in words if w not in _FILLER]
    if not words:
        return ""
    verb = words[0]
    rest = _words_to_numbers(words[1:])
    if verb in {"approve", "show"}:
        nums = [w for w in rest if w.isdigit()]
        has_version = "version" in rest
        if verb == "approve" and has_version and len(nums) == 2:
            return f"approve {nums[0]} v{nums[1]}"
        if len(nums) == 1 and not has_version:
            return f"{verb} {nums[0]}"
        return f"{verb} " + " ".join(rest)  # left ambiguous on purpose
    if verb == "reject" and rest and rest[0].isdigit():
        reason = " ".join(words[2:])
        return f"reject {rest[0]} {reason}".strip()
    if verb in {"list", "queue", "status"}:
        return "list"
    return transcript.strip()
