"""Researcher: collects input for the other agents.

Sources here read local fixture files only (an RSS file of job posts, a JSON
inbox export). A live source would implement the same ``Source`` protocol;
see docs/adding-an-agent.md. This repo deliberately ships no scrapers.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Protocol

from ..models import Lead

_TAG = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub(" ", text or ""))).strip()


class Source(Protocol):
    def fetch(self) -> Iterable[Lead]: ...


@dataclass(frozen=True)
class RssFileSource:
    """Job posts from an RSS 2.0 file on disk."""

    path: Path
    profile: str

    def fetch(self) -> Iterable[Lead]:
        # Local, trusted fixture. For feeds from the internet use defusedxml.
        root = ET.parse(self.path).getroot()  # noqa: S314
        for item in root.iter("item"):
            guid = item.findtext("guid") or item.findtext("link") or ""
            yield Lead(
                profile=self.profile,
                source_id=guid.strip(),
                title=_clean(item.findtext("title")),
                body=_clean(item.findtext("description")),
                contact_name=_clean(item.findtext("author")) or "Hiring manager",
                reply_to=(item.findtext("link") or "").strip(),
            )


@dataclass(frozen=True)
class JsonInboxSource:
    """Customer emails from a JSON export: [{id, from_name, from, subject, body}]."""

    path: Path
    profile: str

    def fetch(self) -> Iterable[Lead]:
        for m in json.loads(self.path.read_text(encoding="utf-8")):
            yield Lead(
                profile=self.profile,
                source_id=str(m["id"]),
                title=m["subject"].strip(),
                body=m["body"].strip(),
                contact_name=m.get("from_name", "").strip(),
                reply_to=m.get("from", "").strip(),
            )


class Researcher:
    """Pulls leads from every source and keeps the relevant ones.

    ``keywords`` maps a profile name to words a lead must mention (any one).
    Profiles without keywords keep everything.
    """

    def __init__(
        self, sources: Sequence[Source], keywords: Mapping[str, Sequence[str]] | None = None
    ) -> None:
        self.sources = list(sources)
        self.keywords = {p: [k.lower() for k in ks] for p, ks in (keywords or {}).items()}

    def relevant(self, lead: Lead) -> bool:
        if not lead.source_id or not lead.body:
            return False
        wanted = self.keywords.get(lead.profile)
        if not wanted:
            return True
        text = f"{lead.title} {lead.body}".lower()
        return any(k in text for k in wanted)

    def collect(self) -> list[Lead]:
        return [lead for s in self.sources for lead in s.fetch() if self.relevant(lead)]
