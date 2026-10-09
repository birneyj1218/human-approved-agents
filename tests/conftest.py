from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from human_approved_agents.app import build
from human_approved_agents.config import Settings
from human_approved_agents.llm import FakeLLM
from human_approved_agents.models import State
from human_approved_agents.orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parents[1]
OWNER = "owner-1"
STRANGER = "stranger-2"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class RecordingSender:
    name = "recording"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, lead, text):  # type: ignore[no-untyped-def]
        self.sent.append((lead.source_id, text))
        return f"rec:{len(self.sent)}"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return replace(
        Settings.from_env({}),
        data_dir=tmp_path / "data",
        profiles_dir=ROOT / "profiles",
        fixtures_dir=ROOT / "fixtures",
        approver_ids=frozenset({OWNER}),
    )


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def make_orch(settings: Settings, clock: Clock, sender: RecordingSender):  # type: ignore[no-untyped-def]
    def _make(llm=None, **overrides) -> Orchestrator:  # type: ignore[no-untyped-def]
        s = replace(settings, **overrides)
        return build(s, llm=llm or FakeLLM(), sender=sender, clock=clock, owner_name="Owner")

    return _make


@pytest.fixture
def orch(make_orch) -> Orchestrator:  # type: ignore[no-untyped-def]
    o = make_orch()
    o.tick()
    return o


def awaiting_ids(o: Orchestrator) -> list[int]:
    return o.store.ids_in_state(State.AWAITING_APPROVAL)


GOOD_EDIT = (
    "Hi Priya,\n\nI build workflow automations in Python and n8n, and I write tests for the "
    "automations I deliver. Happy to talk through your form-to-CRM sync on a short call.\n\n"
    "Sam Rivera"
)
