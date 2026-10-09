import itertools

import pytest

from human_approved_agents.models import State
from human_approved_agents.state_machine import (
    TERMINAL,
    TRANSITIONS,
    InvalidTransition,
    check_transition,
)

HAPPY_PATH = [
    State.NEW,
    State.DRAFTED,
    State.REVIEWED,
    State.AWAITING_APPROVAL,
    State.APPROVED,
    State.SENT,
]


def test_happy_path_is_allowed():
    for a, b in itertools.pairwise(HAPPY_PATH):
        actor = "human:1" if a is State.AWAITING_APPROVAL else "system"
        check_transition(a, b, actor=actor)


@pytest.mark.parametrize("target", [State.APPROVED, State.REJECTED, State.EDITED])
def test_only_a_human_leaves_awaiting_approval(target):
    with pytest.raises(InvalidTransition):
        check_transition(State.AWAITING_APPROVAL, target, actor="system")
    with pytest.raises(InvalidTransition):
        check_transition(State.AWAITING_APPROVAL, target, actor="drafter")
    check_transition(State.AWAITING_APPROVAL, target, actor="human:1")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (State.NEW, State.APPROVED),
        (State.DRAFTED, State.SENT),
        (State.REVIEWED, State.APPROVED),
        (State.EDITED, State.APPROVED),
        (State.EDITED, State.AWAITING_APPROVAL),
        (State.REJECTED, State.APPROVED),
        (State.SENT, State.APPROVED),
        (State.APPROVED, State.EDITED),
    ],
)
def test_shortcuts_are_refused(a, b):
    with pytest.raises(InvalidTransition):
        check_transition(a, b, actor="human:1")


def test_nothing_reaches_sent_except_from_approved():
    sources = [s for s, nxt in TRANSITIONS.items() if State.SENT in nxt]
    assert sources == [State.APPROVED]


def test_terminal_states():
    assert {State.REJECTED, State.SENT} == TERMINAL


def test_every_state_has_a_rule():
    assert set(TRANSITIONS) == set(State)
