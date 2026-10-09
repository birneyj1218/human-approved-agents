"""Reviewer: checks a draft against written rules. Deterministic, no LLM.

Blocking checks (the item cannot be approved until fixed):
  * length within min/max words
  * no banned phrases (profile rules plus "never say" lessons)
  * every number in the draft appears in the facts or in the incoming message
  * every claim keyword (licensed, warranty, years...) is backed by a fact
  * sign-off present; no unfilled placeholders like [Name] or {{x}}

Warnings (shown on the card, not blocking): too many exclamation marks,
shouting in capitals.

The fact check is a heuristic. It catches invented numbers and listed claim
types; it cannot prove a sentence is true. That is what the human is for.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..memory import word_count
from ..models import Issue, Lead, Review
from ..profiles import Profile

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PLACEHOLDER = re.compile(r"\[[A-Z][A-Za-z ]*\]|\{\{.*?\}\}|<[A-Z_]+>")
_SHOUT = re.compile(r"\b[A-Z]{4,}\b")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


class Reviewer:
    def review(
        self, profile: Profile, lead: Lead, draft: str, banned: Sequence[str] = ()
    ) -> Review:
        r = profile.rules
        issues: list[Issue] = []
        words = word_count(draft)
        lower = draft.lower()
        evidence = " ".join(profile.facts) + " " + lead.title + " " + lead.body
        evidence_lower = evidence.lower()

        if words > r.max_words:
            issues.append(Issue("length", f"{words} words; the limit is {r.max_words}"))
        if words < r.min_words:
            issues.append(Issue("length", f"{words} words; the minimum is {r.min_words}"))

        for phrase in [*r.banned_phrases, *banned]:
            if phrase.lower() in lower:
                issues.append(Issue("banned_phrase", f'uses banned phrase "{phrase}"'))

        allowed = _numbers(evidence)
        for n in sorted(_numbers(draft) - allowed):
            issues.append(Issue("unsupported_fact", f'number "{n}" is not in the facts file'))

        for kw in r.claim_keywords:
            if re.search(rf"\b{re.escape(kw.lower())}", lower) and kw.lower() not in evidence_lower:
                issues.append(Issue("unsupported_fact", f'claim "{kw}" is not backed by a fact'))

        if r.sign_off and r.sign_off.strip() not in draft:
            issues.append(Issue("sign_off", f'missing sign-off "{r.sign_off}"'))

        if _PLACEHOLDER.search(draft):
            issues.append(Issue("placeholder", "contains an unfilled placeholder"))

        if draft.count("!") > r.max_exclamations:
            issues.append(
                Issue("tone", f"{draft.count('!')} exclamation marks; keep it calm", blocking=False)
            )
        shouting = [w for w in _SHOUT.findall(draft) if w not in evidence]
        if shouting:
            issues.append(
                Issue("tone", f"capitals read as shouting: {shouting[0]}", blocking=False)
            )

        return Review(issues=tuple(issues), word_count=words)
