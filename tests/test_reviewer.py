from pathlib import Path

import pytest

from human_approved_agents.agents.reviewer import Reviewer
from human_approved_agents.models import Lead
from human_approved_agents.profiles import load_profile

ROOT = Path(__file__).resolve().parents[1]
ROOF = load_profile(ROOT / "profiles" / "blue-gable-roofing.toml")
LEAD = Lead("blue-gable-roofing", "x", "Leak over 2 windows", "It leaks at 3 spots.", "Dana")
OK = (
    "Hi Dana,\n\nFor an active leak we can place a temporary tarp, usually within 48 hours of the "
    "inspection. Free inspections are booked Monday to Friday, 8 am to 5 pm.\n\n"
    "The Blue Gable Roofing team"
)


def rules(draft, banned=()):
    return {i.rule for i in Reviewer().review(ROOF, LEAD, draft, banned).issues}


def test_clean_draft_passes():
    review = Reviewer().review(ROOF, LEAD, OK)
    assert review.passed
    assert review.issues == ()
    assert review.word_count > 25


@pytest.mark.parametrize(
    "claim",
    [
        "We offer same-day repairs.",
        "Ask about financing.",
        "We have won an award.",
        "We have 20 years in business.",
    ],
)
def test_claims_not_in_facts_are_blocked(claim):
    assert "unsupported_fact" in rules(OK.replace("Free inspections", claim + " Free inspections"))


def test_numbers_must_come_from_facts_or_the_message():
    assert "unsupported_fact" in rules(OK.replace("48 hours", "24 hours"))
    assert "unsupported_fact" in rules(OK + " Prices start at $4,500.")
    # Numbers the customer used are fine to repeat.
    assert rules(OK.replace("Hi Dana,", "Hi Dana, thanks for flagging the 3 spots.")) == set()


def test_backed_claims_pass():
    assert rules(OK.replace("Free", "We are licensed and insured. Free")) == set()


def test_length_banned_signoff_placeholder():
    assert "length" in rules("Hi. The Blue Gable Roofing team")
    assert "length" in rules(OK + " word" * 200)
    assert "banned_phrase" in rules(OK.replace("Hi Dana,", "Hi Dana, act now!"))
    assert "banned_phrase" in rules(OK, banned=["temporary tarp"])
    assert "sign_off" in rules(OK.replace("The Blue Gable Roofing team", "Bye"))
    assert "placeholder" in rules(OK.replace("Dana", "[Customer Name]"))
    assert "placeholder" in rules(OK.replace("Dana", "{{name}}"))


def test_tone_issues_are_warnings_only():
    review = Reviewer().review(ROOF, LEAD, OK.replace("Hi Dana,", "Hi Dana!! VERY URGENT"))
    assert {i.rule for i in review.issues} == {"tone"}
    assert review.passed
