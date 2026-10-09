"""End-to-end demo: fixtures in, fake LLM, scripted human at the CLI approver.

    python -m human_approved_agents.demo

Nothing leaves the machine. SEND_ENABLED stays false, so approved items are
marked "DRY RUN, not sent". State goes to a temporary directory unless
--data-dir is given.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .agents import Drafter
from .app import build
from .audit import verify
from .config import Settings
from .llm import FakeLLM, Message
from .models import State
from .orchestrator import Orchestrator
from .voice import transcript_to_command

OWNER = "owner-1"
STRANGER = "someone-else-99"
_SRC_ROOT = Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    """Repo checkout (editable install) or the current directory (Docker image)."""
    return _SRC_ROOT if (_SRC_ROOT / "profiles").is_dir() else Path.cwd()


class DemoLLM(FakeLLM):
    """FakeLLM that makes one realistic mistake so the Reviewer has work to do:
    the first draft for the garage leak opens with a banned phrase and invents
    "25 years of experience". The redraft (with reviewer feedback) is clean."""

    def complete(self, messages: Sequence[Message], *, temperature: float = 0.3) -> str:
        text = super().complete(messages, temperature=temperature)
        prompt = messages[-1]["content"]
        if "garage" in prompt and "reviewer" not in prompt:
            first, _, rest = text.partition("\n\n")
            text = (
                f"{first}\n\nI hope this email finds you well. We have 25 years of experience "
                f"with leaks like this. {rest}"
            )
        return text


class FixedClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def _say(msg: str = "") -> None:
    print(msg)


def _step(title: str) -> None:
    _say()
    _say("=" * 72)
    _say(title)
    _say("=" * 72)


def _human(orch: Orchestrator, user: str, text: str, source: str = "text") -> None:
    flat = " / ".join(line for line in text.splitlines() if line.strip())
    shown = flat if len(flat) < 70 else flat[:67] + "..."
    _say(f"\n[{user}{' (voice)' if source == 'voice' else ''}] {shown}")
    for m in orch.handle_command(user, text, source=source):
        _say(m)


def _find(orch: Orchestrator, source_id: str) -> int:
    for state in State:
        for i in orch.store.ids_in_state(state):
            item = orch.store.get(i)
            if item and item.lead.source_id == source_id:
                return i
    raise LookupError(source_id)


def run(data_dir: Path) -> int:
    settings = replace(
        Settings.from_env({}),
        data_dir=data_dir,
        profiles_dir=_project_root() / "profiles",
        fixtures_dir=_project_root() / "fixtures",
        approver_ids=frozenset({OWNER}),
        max_commands_per_minute=60,  # the scripted human types faster than a real one
    )
    orch = build(settings, llm=DemoLLM(), clock=FixedClock(), owner_name="Owner")

    _step("1. Agents run: Researcher -> Drafter -> Reviewer -> cards for approval")
    messages = orch.tick()
    leak = _find(orch, "bgr-msg-001")
    item = orch.store.get(leak)
    assert item is not None
    first = item.versions[0]
    assert first.review is not None
    _say(f"Reviewer blocked #{leak} v1 and sent it back to the Drafter:")
    for issue in first.review.issues:
        _say(f"  - {issue.message}")
    _say("(The logo-design job post was skipped by the Researcher: not relevant.)\n")
    for m in messages:
        _say(m)
        _say()

    jobs = [_find(orch, f"jobs.example.com/{n}") for n in (1001, 1002, 1004)]
    quote = _find(orch, "bgr-msg-002")

    _step("2. The human decides. Only explicit commands from the allowlist count")
    _human(orch, STRANGER, f"approve {leak}")
    _human(orch, OWNER, "looks good")
    _human(orch, OWNER, f"approve {leak}")
    _human(orch, OWNER, f"approve {leak}")
    _human(orch, OWNER, "approve all")

    _step("3. An edit creates a new version that needs its own approval")
    edited = (
        "Hi Priya,\n\nI build workflow automations in Python and n8n, and I write tests for the "
        "automations I deliver. For your form-to-CRM sync I would test it against sample leads "
        "before switching it on.\n\nWould a short call this week work?\n\nSam Rivera"
    )
    _human(orch, OWNER, f"edit {jobs[0]}: {edited}")
    _human(orch, OWNER, f"approve {jobs[0]} v1")
    _human(orch, OWNER, f"approve {jobs[0]}")

    _step("4. Rejection with a reason, and an explicit rule. Both become lessons")
    _human(orch, OWNER, f"reject {jobs[1]} too generic; ask which billing tool they use")
    _human(orch, OWNER, 'lesson: never say "circle back"')

    _step("5. Voice (transcript only; no model is loaded in the demo)")
    for heard in (
        f"Approve number {_spoken(jobs[2])}.",
        f"Approve {_spoken(jobs[2])} version one.",
    ):
        cmd = transcript_to_command(heard)
        _say(f'\nTranscript: "{heard}" -> command: "{cmd}"')
        _human(orch, OWNER, cmd, source="voice")

    _step("6. Delivery. SEND_ENABLED is false, so this is a dry run")
    for m in orch.deliver().messages():
        _say(m)
    _say(
        f"\n#{quote} got no reply from the human, so it is still waiting. Silence is not approval."
    )

    _step("7. Where everything ended up")
    for i in sorted(orch.store.ids_in_state(*State)):
        it = orch.store.get(i)
        assert it is not None
        v = it.current.number if it.current else 0
        _say(f"#{i:<3} {it.state.value:<18} v{v}  {it.lead.title}")

    _say("\nLessons the Drafter will now see for the freelancer profile:")
    for lesson in orch.memory.lessons_for("freelancer"):
        _say(f"  - {lesson}")
    _say("Banned phrases added by lessons: " + ", ".join(orch.memory.banned_phrases("freelancer")))

    probe = orch.store.get(jobs[1])
    assert probe is not None
    prompt = Drafter.build_messages(
        orch.profiles["freelancer"],
        probe.lead,
        lessons=orch.memory.lessons_for("freelancer"),
        banned=orch.memory.banned_phrases("freelancer"),
    )[0]["content"]
    _say("\n(Excerpt of the next Drafter prompt)")
    _say(prompt[prompt.index("LESSONS:") :].strip())

    ok, msg = verify(settings.audit_path)
    _say(f"\nAudit log: {len(orch.audit.entries())} entries, {msg}.")
    _say(f"Files: {settings.audit_path} and {settings.db_path}")
    return 0 if ok else 1


_NUM_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _spoken(n: int) -> str:
    return _NUM_WORDS[n] if n < 10 else str(n)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--data-dir", type=Path, help="keep state here instead of a temp dir")
    args = parser.parse_args(argv)
    if args.data_dir:
        return run(args.data_dir)
    with tempfile.TemporaryDirectory(prefix="haa-demo-") as tmp:
        return run(Path(tmp))


if __name__ == "__main__":
    sys.exit(main())
