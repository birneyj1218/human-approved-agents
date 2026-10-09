"""The approval gate: the only place a human command changes an item.

Rules (see docs/approval-rules.md):

1. Only user IDs on the allowlist can approve, reject, edit or add lessons.
2. An approval covers exactly one item and one version. "approve all" and
   "looks good" approve nothing.
3. An edit creates a new version. The new version is reviewed again and
   needs its own approval; the old approval (if any) never carries over.
4. Silence is not approval. Nothing times out into "approved".
5. A version with blocking review issues cannot be approved; edit or reject.
6. Voice commands must name the version ("approve 3 version 2"), so a
   misheard number fails safe instead of approving the wrong item.
7. Approving twice is a no-op. Approving a rejected item is refused.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..audit import AuditLog
from ..clock import Clock, utcnow
from ..memory import Memory
from ..models import Item, State, Version
from ..ratelimit import SlidingWindowLimiter
from ..state_machine import check_transition
from ..store import Store
from .cards import HELP, render_card, render_summary
from .commands import Command, parse_command


@dataclass(frozen=True)
class GateResult:
    reply: str
    changed: bool = False
    item_id: int | None = None


class ApprovalGate:
    def __init__(
        self,
        *,
        store: Store,
        memory: Memory,
        audit: AuditLog,
        approvers: frozenset[str],
        limiter: SlidingWindowLimiter,
        clock: Clock = utcnow,
    ) -> None:
        self.store = store
        self.memory = memory
        self.audit = audit
        self.approvers = approvers
        self.limiter = limiter
        self.clock = clock

    # ------------------------------------------------------------------
    def handle(self, user_id: str, raw: str, *, source: str = "text") -> GateResult:
        cmd = parse_command(raw)
        actor = f"human:{user_id}"

        if cmd.verb in {"help", "unknown"}:
            return GateResult(HELP if cmd.verb == "help" else "")
        if user_id not in self.approvers:
            self.audit.record(
                "denied",
                actor=actor,
                item_id=cmd.item_id,
                reason="not on allowlist",
                command=cmd.verb,
                source=source,
            )
            return GateResult("You are not on the approver list. Nothing was changed.")
        if not self.limiter.allow(user_id):
            self.audit.record("rate_limited", actor=actor, item_id=cmd.item_id, command=cmd.verb)
            return GateResult(
                "Too many commands in a minute. Nothing was changed; try again shortly."
            )

        if cmd.verb == "approval_like":
            return GateResult("That is not an approval. To send an item reply: approve N")
        if cmd.verb == "ambiguous":
            return GateResult("An approval covers one item. Reply: approve N (one number).")
        if cmd.verb == "list":
            items = [self.store.get(i) for i in self.store.ids_in_state(State.AWAITING_APPROVAL)]
            return GateResult(render_summary([i for i in items if i is not None]))
        if cmd.verb == "lesson":
            phrase = self.memory.record_rule(cmd.text, self.clock())
            self.audit.record("lesson_added", actor=actor, text=cmd.text, banned_phrase=phrase)
            if phrase:
                return GateResult(
                    f'Noted. "{phrase}" is now a banned phrase the Reviewer enforces.'
                )
            return GateResult("Noted. The Drafter will see this lesson from now on.")

        assert cmd.item_id is not None
        item = self.store.get(cmd.item_id)
        if item is None:
            return GateResult(f"There is no item #{cmd.item_id}.")
        if cmd.verb == "show":
            return GateResult(
                render_card(item) if item.current else f"#{item.id} has no draft yet."
            )
        if cmd.verb == "approve":
            return self._approve(item, cmd, actor, source)
        if cmd.verb == "reject":
            return self._reject(item, cmd, actor)
        if cmd.verb == "edit":
            return self._edit(item, cmd, actor, source)
        return GateResult("")  # pragma: no cover - parse_command has no other verbs

    # ------------------------------------------------------------------
    def _not_awaiting(self, item: Item) -> str:
        if item.state in {State.APPROVED, State.SENT}:
            return f"#{item.id} v{item.approved_version} is already approved. Nothing to do."
        if item.state is State.REJECTED:
            return f"#{item.id} was rejected. It cannot be approved or edited."
        return f"#{item.id} has a version still being drafted or reviewed. Wait for its card."

    def _approve(self, item: Item, cmd: Command, actor: str, source: str) -> GateResult:
        if item.state is not State.AWAITING_APPROVAL:
            return GateResult(self._not_awaiting(item), item_id=item.id)
        current = item.current
        assert current is not None
        if source == "voice" and cmd.version is None:
            return GateResult(
                f'Voice approvals must say the version, e.g. "approve {item.id} version '
                f'{current.number}". Nothing was changed.',
                item_id=item.id,
            )
        if cmd.version is not None and cmd.version != current.number:
            self.audit.record(
                "stale_approval_refused",
                actor=actor,
                item_id=item.id,
                requested_version=cmd.version,
                current_version=current.number,
            )
            return GateResult(
                f"#{item.id} v{cmd.version} is not the current version (v{current.number}). "
                "Nothing was approved.",
                item_id=item.id,
            )
        if current.review is None or not current.review.passed:
            return GateResult(
                f"#{item.id} v{current.number} has blocking review issues. "
                f"Edit it (edit {item.id}: ...) or reject it.",
                item_id=item.id,
            )
        check_transition(item.state, State.APPROVED, actor=actor)
        item.state = State.APPROVED
        item.approved_version = current.number
        item.approved_hash = current.content_hash
        item.approved_by = actor
        self.store.save_state(item)
        now = self.clock()
        self.store.add_decision(item.id, current.number, "approved", actor, "", now)
        self.audit.record(
            "transition",
            actor=actor,
            item_id=item.id,
            version=current.number,
            frm=State.AWAITING_APPROVAL.value,
            to=State.APPROVED.value,
            content_hash=current.content_hash,
            source=source,
        )
        return GateResult(f"Approved #{item.id} v{current.number}.", changed=True, item_id=item.id)

    def _reject(self, item: Item, cmd: Command, actor: str) -> GateResult:
        if item.state is not State.AWAITING_APPROVAL:
            return GateResult(self._not_awaiting(item), item_id=item.id)
        current = item.current
        assert current is not None
        check_transition(item.state, State.REJECTED, actor=actor)
        item.state = State.REJECTED
        self.store.save_state(item)
        now = self.clock()
        self.store.add_decision(item.id, current.number, "rejected", actor, cmd.text, now)
        self.memory.record_rejection(
            profile=item.lead.profile, item_id=item.id, reason=cmd.text, now=now
        )
        self.audit.record(
            "transition",
            actor=actor,
            item_id=item.id,
            version=current.number,
            frm=State.AWAITING_APPROVAL.value,
            to=State.REJECTED.value,
            reason=cmd.text,
        )
        return GateResult(
            f"Rejected #{item.id}. It will not be sent.", changed=True, item_id=item.id
        )

    def _edit(self, item: Item, cmd: Command, actor: str, source: str) -> GateResult:
        if item.state is not State.AWAITING_APPROVAL:
            return GateResult(self._not_awaiting(item), item_id=item.id)
        current = item.current
        assert current is not None
        if cmd.version is not None and cmd.version != current.number:
            return GateResult(
                f"#{item.id} is now at v{current.number}; your edit was for v{cmd.version}. "
                "Nothing was changed.",
                item_id=item.id,
            )
        if cmd.text.strip() == current.text.strip():
            return GateResult("That text is the same as the current version. Nothing changed.")
        now = self.clock()
        check_transition(item.state, State.EDITED, actor=actor)
        new = Version(
            number=current.number + 1, text=cmd.text.strip(), author=actor, created_at=now
        )
        self.store.add_version(item.id, new)
        item.state = State.EDITED
        # An edit always clears any earlier approval data.
        item.approved_version = item.approved_hash = item.approved_by = None
        self.store.save_state(item)
        self.store.add_decision(item.id, current.number, "edited", actor, "", now)
        lessons = self.memory.record_edit(
            profile=item.lead.profile, item_id=item.id, before=current.text, after=new.text, now=now
        )
        self.audit.record(
            "transition",
            actor=actor,
            item_id=item.id,
            version=new.number,
            frm=State.AWAITING_APPROVAL.value,
            to=State.EDITED.value,
            source=source,
            lessons=len(lessons),
        )
        return GateResult(
            f"Saved your edit as #{item.id} v{new.number}. It will be reviewed and posted for "
            "approval. The earlier version can no longer be approved.",
            changed=True,
            item_id=item.id,
        )
