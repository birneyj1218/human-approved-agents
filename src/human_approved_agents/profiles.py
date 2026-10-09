"""A profile is one voice the system writes in: its facts, tone and rules.

Profiles are TOML files in ``profiles/``. The facts list is the only source
of claims the Drafter may make; the Reviewer enforces that.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Rules:
    min_words: int = 20
    max_words: int = 180
    banned_phrases: tuple[str, ...] = ()
    claim_keywords: tuple[str, ...] = ()
    max_exclamations: int = 1
    sign_off: str = ""


@dataclass(frozen=True)
class Profile:
    name: str
    display_name: str
    task: str
    tone: str
    facts: tuple[str, ...]
    rules: Rules = field(default_factory=Rules)
    # Where the Researcher finds input for this profile: {type, path, keywords}
    source: dict[str, object] = field(default_factory=dict)


def load_profile(path: Path) -> Profile:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    r = data.get("rules", {})
    return Profile(
        name=data["name"],
        display_name=data.get("display_name", data["name"]),
        task=data["task"],
        tone=data.get("tone", ""),
        facts=tuple(data.get("facts", [])),
        rules=Rules(
            min_words=int(r.get("min_words", 20)),
            max_words=int(r.get("max_words", 180)),
            banned_phrases=tuple(r.get("banned_phrases", [])),
            claim_keywords=tuple(r.get("claim_keywords", [])),
            max_exclamations=int(r.get("max_exclamations", 1)),
            sign_off=r.get("sign_off", ""),
        ),
        source=dict(data.get("source", {})),
    )


def load_profiles(directory: Path) -> dict[str, Profile]:
    profiles = {}
    for path in sorted(directory.glob("*.toml")):
        p = load_profile(path)
        profiles[p.name] = p
    if not profiles:
        raise FileNotFoundError(f"no profiles found in {directory}")
    return profiles
