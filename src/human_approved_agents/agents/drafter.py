"""Drafter: writes a reply with an LLM, using only the profile's facts."""

from __future__ import annotations

from collections.abc import Sequence

from ..llm import LLM, Message
from ..models import Lead
from ..profiles import Profile

SYSTEM = """You write {task} for {display_name}.
Tone: {tone}

Use ONLY the facts listed under FACTS. Do not invent experience, numbers,
credentials, prices, dates or guarantees. If the request needs a fact that is
not listed, say you will confirm it rather than guessing.
Length: {min_words}-{max_words} words. End with the sign-off exactly as given.
Never use these phrases: {banned}.
Return only the message text, no subject line and no commentary.

FACTS:
{facts}

LESSONS:
{lessons}

SIGN-OFF: {sign_off}"""

USER = """Write a reply to this.

TITLE: {title}
CONTACT: {contact}
BODY: {body}"""


class Drafter:
    def __init__(self, llm: LLM, temperature: float = 0.4) -> None:
        self.llm = llm
        self.temperature = temperature

    @staticmethod
    def build_messages(
        profile: Profile,
        lead: Lead,
        *,
        lessons: Sequence[str] = (),
        banned: Sequence[str] = (),
        feedback: Sequence[str] = (),
    ) -> list[Message]:
        r = profile.rules
        all_banned = [*r.banned_phrases, *banned]
        system = SYSTEM.format(
            task=profile.task,
            display_name=profile.display_name,
            tone=profile.tone,
            min_words=r.min_words,
            max_words=r.max_words,
            banned=", ".join(f'"{b}"' for b in all_banned) or "(none)",
            facts="\n".join(f"- {f}" for f in profile.facts),
            lessons="\n".join(f"- {s}" for s in lessons) or "- (none yet)",
            sign_off=r.sign_off,
        )
        user = USER.format(title=lead.title, contact=lead.contact_name, body=lead.body)
        if feedback:
            user += "\n\nYour previous draft was rejected by the reviewer. Fix these:\n"
            user += "\n".join(f"- {f}" for f in feedback)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def draft(
        self,
        profile: Profile,
        lead: Lead,
        *,
        lessons: Sequence[str] = (),
        banned: Sequence[str] = (),
        feedback: Sequence[str] = (),
    ) -> str:
        messages = self.build_messages(
            profile, lead, lessons=lessons, banned=banned, feedback=feedback
        )
        return self.llm.complete(messages, temperature=self.temperature).strip()
