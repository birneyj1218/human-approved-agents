"""Orchestrator: moves items through the state machine.

Agents never talk to each other directly. The orchestrator asks each one for
its piece of work, records the result, and moves the item to the next state.
It returns the messages to post (approval cards, delivery notes) instead of
posting them itself, so the same loop runs behind the CLI, Discord, or tests.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .agents import Drafter, Researcher, Reviewer
from .approval.cards import render_card
from .approval.gate import ApprovalGate
from .audit import AuditLog
from .clock import Clock, utcnow
from .llm import LLMError
from .memory import Memory
from .models import Item, State, Version
from .profiles import Profile
from .senders import Delivery, DeliveryRefused, RateLimited
from .state_machine import check_transition
from .store import Store

SYSTEM = "system"


@dataclass
class Outbox:
    """Messages for the approval channel produced by one step."""

    cards: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def extend(self, other: Outbox) -> None:
        self.cards += other.cards
        self.notes += other.notes

    def messages(self) -> list[str]:
        return [*self.notes, *self.cards]


class Orchestrator:
    def __init__(
        self,
        *,
        profiles: dict[str, Profile],
        researcher: Researcher,
        drafter: Drafter,
        reviewer: Reviewer,
        store: Store,
        memory: Memory,
        audit: AuditLog,
        gate: ApprovalGate,
        delivery: Delivery,
        max_redrafts: int = 2,
        clock: Clock = utcnow,
    ) -> None:
        self.profiles = profiles
        self.researcher = researcher
        self.drafter = drafter
        self.reviewer = reviewer
        self.store = store
        self.memory = memory
        self.audit = audit
        self.gate = gate
        self.delivery = delivery
        self.max_redrafts = max_redrafts
        self.clock = clock
        self._lock = threading.RLock()

    # -- helpers ---------------------------------------------------------
    def _move(self, item: Item, target: State, *, actor: str = SYSTEM, **detail: object) -> None:
        check_transition(item.state, target, actor=actor)
        frm = item.state
        item.state = target
        self.store.save_state(item)
        detail.setdefault("version", item.current.number if item.current else None)
        self.audit.record(
            "transition", actor=actor, item_id=item.id, frm=frm.value, to=target.value, **detail
        )

    def _profile(self, item: Item) -> Profile:
        return self.profiles[item.lead.profile]

    # -- steps -----------------------------------------------------------
    def ingest(self) -> int:
        added = 0
        with self._lock:
            for lead in self.researcher.collect():
                if lead.profile not in self.profiles:
                    continue
                item = self.store.add_item(lead, self.clock())
                if item is not None:
                    added += 1
                    self.audit.record(
                        "created",
                        actor="researcher",
                        item_id=item.id,
                        profile=lead.profile,
                        source_id=lead.source_id,
                    )
        return added

    def _draft(self, item: Item, feedback: list[str]) -> bool:
        profile = self._profile(item)
        try:
            text = self.drafter.draft(
                profile,
                item.lead,
                lessons=self.memory.lessons_for(profile.name),
                banned=self.memory.banned_phrases(profile.name),
                feedback=feedback,
            )
        except LLMError as exc:
            self.audit.record("draft_error", actor="drafter", item_id=item.id, error=str(exc))
            return False
        number = (item.current.number if item.current else 0) + 1
        version = Version(number=number, text=text, author="drafter", created_at=self.clock())
        self.store.add_version(item.id, version)
        item.versions.append(version)
        return True

    def _review(self, item: Item) -> None:
        current = item.current
        assert current is not None
        profile = self._profile(item)
        review = self.reviewer.review(
            profile, item.lead, current.text, banned=self.memory.banned_phrases(profile.name)
        )
        self.store.set_review(item.id, current.number, review)
        item.versions[-1] = Version(
            current.number, current.text, current.author, current.created_at, review
        )
        self._move(
            item,
            State.REVIEWED,
            actor="reviewer",
            passed=review.passed,
            issues=[i.rule for i in review.issues],
        )

    def advance(self, item: Item) -> Outbox:
        """Move one item forward as far as the agents can take it."""
        out = Outbox()
        while True:
            if item.state is State.NEW:
                if not self._draft(item, []):
                    return out  # retried next tick
                self._move(item, State.DRAFTED, actor="drafter")
            elif item.state in {State.DRAFTED, State.EDITED}:
                self._review(item)
            elif item.state is State.REVIEWED:
                current = item.current
                assert current is not None
                assert current.review is not None
                can_redraft = (
                    not current.review.passed
                    and current.author == "drafter"
                    and item.redrafts < self.max_redrafts
                )
                if can_redraft:
                    feedback = [i.message for i in current.review.issues if i.blocking]
                    if not self._draft(item, feedback):
                        return out
                    item.redrafts += 1
                    self._move(item, State.DRAFTED, actor="drafter", redraft=item.redrafts)
                    continue
                # Passed, or out of redrafts, or written by the human: show it.
                self._move(item, State.AWAITING_APPROVAL)
                out.cards.append(render_card(item))
                return out
            else:
                return out

    def process(self) -> Outbox:
        out = Outbox()
        with self._lock:
            for item_id in self.store.ids_in_state(
                State.NEW, State.DRAFTED, State.EDITED, State.REVIEWED
            ):
                item = self.store.get(item_id)
                if item is not None:
                    out.extend(self.advance(item))
        return out

    def deliver(self) -> Outbox:
        out = Outbox()
        with self._lock:
            for item_id in self.store.ids_in_state(State.APPROVED):
                item = self.store.get(item_id)
                assert item is not None
                try:
                    result = self.delivery.deliver(item)
                except RateLimited as exc:
                    self.audit.record(
                        "send_deferred", actor=SYSTEM, item_id=item.id, reason=str(exc)
                    )
                    out.notes.append(f"#{item.id}: {exc}")
                    continue
                except DeliveryRefused as exc:
                    self.audit.record(
                        "send_refused", actor=SYSTEM, item_id=item.id, reason=str(exc)
                    )
                    out.notes.append(f"#{item.id}: refused to send: {exc}")
                    continue
                self._move(
                    item,
                    State.SENT,
                    actor="sender",
                    mode=result.mode,
                    receipt=result.receipt,
                    approved_by=item.approved_by,
                    version=item.approved_version,
                )
                label = "DRY RUN, not sent" if result.mode == "dry_run" else "Sent"
                out.notes.append(
                    f"#{item.id} v{item.approved_version}: {label} ({result.receipt})."
                )
        return out

    def handle_command(self, user_id: str, text: str, *, source: str = "text") -> list[str]:
        """Apply one human message; return replies plus any new cards."""
        with self._lock:
            result = self.gate.handle(user_id, text, source=source)
            out = Outbox(notes=[result.reply] if result.reply else [])
            if result.changed:
                out.extend(self.process())
            return out.messages()

    def tick(self) -> list[str]:
        """One full pass: collect, draft/review, deliver approved items."""
        with self._lock:
            self.ingest()
            out = self.process()
            out.extend(self.deliver())
            return out.messages()

    def awaiting(self) -> list[Item]:
        items = [self.store.get(i) for i in self.store.ids_in_state(State.AWAITING_APPROVAL)]
        return [i for i in items if i is not None]
