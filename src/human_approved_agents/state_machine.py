"""The allowed state transitions. Anything not listed here raises.

    new -> drafted -> reviewed -> awaiting_approval -> approved -> sent
                        ^  |                |
           (redraft)    |  v                +--> rejected
                     drafted                +--> edited -> reviewed -> awaiting_approval

Only a human command can move an item out of ``awaiting_approval``.
"""

from __future__ import annotations

from .models import State

TRANSITIONS: dict[State, frozenset[State]] = {
    State.NEW: frozenset({State.DRAFTED}),
    State.DRAFTED: frozenset({State.REVIEWED}),
    State.REVIEWED: frozenset({State.DRAFTED, State.AWAITING_APPROVAL}),
    State.AWAITING_APPROVAL: frozenset({State.APPROVED, State.REJECTED, State.EDITED}),
    State.EDITED: frozenset({State.REVIEWED}),
    State.APPROVED: frozenset({State.SENT}),
    State.REJECTED: frozenset(),
    State.SENT: frozenset(),
}

# Transitions that only a human approver may cause.
HUMAN_ONLY: frozenset[tuple[State, State]] = frozenset(
    {
        (State.AWAITING_APPROVAL, State.APPROVED),
        (State.AWAITING_APPROVAL, State.REJECTED),
        (State.AWAITING_APPROVAL, State.EDITED),
    }
)

TERMINAL: frozenset[State] = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)


class InvalidTransition(Exception):
    def __init__(self, current: State, target: State) -> None:
        super().__init__(f"cannot move from {current} to {target}")
        self.current = current
        self.target = target


def check_transition(current: State, target: State, *, actor: str) -> None:
    """Raise unless ``current -> target`` is allowed for ``actor``.

    ``actor`` is ``"system"`` for agents and ``"human:<id>"`` for an approver.
    """
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(current, target)
    if (current, target) in HUMAN_ONLY and not actor.startswith("human:"):
        raise InvalidTransition(current, target)
