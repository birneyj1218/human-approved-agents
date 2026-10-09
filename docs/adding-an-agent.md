# Adding an agent

Every agent is a plain class with one job. The Orchestrator calls it, stores what it returns and decides the next state. Agents never call each other and never send anything.

## 1. A new source for the Researcher

Implement the `Source` protocol: a `fetch()` that yields `Lead` objects with a stable `source_id` (used to skip leads already seen).

```python
import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from human_approved_agents.models import Lead


@dataclass(frozen=True)
class CsvLeadsSource:
    path: Path
    profile: str

    def fetch(self) -> Iterable[Lead]:
        with self.path.open() as f:
            for row in csv.DictReader(f):
                yield Lead(self.profile, row["id"], row["subject"], row["message"],
                           row["name"], row["email"])
```

Register the type in `app.build_sources()` and point a profile at it:

```toml
[source]
type = "csv"
path = "leads.csv"
```

If the source is a live API, respect its terms of service and rate limits, and keep credentials in environment variables. This repo ships fixtures only.

## 2. A new kind of check (Reviewer)

Add a check to `Reviewer.review()` that appends an `Issue(rule, message, blocking)`. Blocking issues stop approval and trigger a redraft; non-blocking ones show on the card as notes. Add a test in `tests/test_reviewer.py` with one passing and one failing draft.

Prefer checks you can explain in one line on the card. If you add an LLM-based check, make it non-blocking until you have seen how often it is wrong.

## 3. A new agent step

Say you want a **Scorer** that rates each lead before drafting and skips weak ones.

1. Add a state or reuse one. Skipping is a terminal outcome, so add `SKIPPED` to `State` and the transition `NEW -> SKIPPED` to `TRANSITIONS`. Leave `HUMAN_ONLY` alone: skipping a lead does not send anything.
2. Write the agent as a class with one method, e.g. `score(profile, lead) -> float`. Give it an injectable dependency (LLM or rules) so tests can fake it.
3. Call it from `Orchestrator.advance()` in the `NEW` branch, record the score in the audit log, and move the item.
4. Wire it in `app.build()`.
5. Tests: one for the transition table (`test_state_machine.py`) and one for the Orchestrator path with a fake scorer.

What you must not do: give an agent a path to `Delivery` or to any state after `awaiting_approval`. `check_transition()` will raise if a non-human actor tries to leave `awaiting_approval`, and the tests check that only `approved` leads to `sent`.

## 4. A new sender

Implement `Sender` (a `name` and `send(lead, text) -> receipt`). Delivery calls it only after the approval, hash, `SEND_ENABLED` and rate-limit checks. Make `send` raise on failure; the item then stays `approved` and the error is visible in the logs. Choose it in `app.build()` (or pass `sender=` in code).

## 5. A new approval channel

A channel only has to do two things: show the strings the Orchestrator returns, and pass each incoming message to `orchestrator.handle_command(user_id, text, source=...)` with an identity the platform vouches for (never a name typed in the message). See `approval/cli.py` (about 40 lines) for the minimum.
