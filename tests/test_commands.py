import pytest

from human_approved_agents.approval.commands import parse_command


@pytest.mark.parametrize(
    ("text", "verb", "item", "version"),
    [
        ("approve 3", "approve", 3, None),
        ("Approve #3", "approve", 3, None),
        ("approve 3 v2", "approve", 3, 2),
        ("approve 3 version 2", "approve", 3, 2),
        ("approve 12.", "approve", 12, None),
        ("reject 4", "reject", 4, None),
        ("show 7", "show", 7, None),
    ],
)
def test_parses_item_commands(text, verb, item, version):
    c = parse_command(text)
    assert (c.verb, c.item_id, c.version) == (verb, item, version)


@pytest.mark.parametrize(
    "text", ["approve all", "approve 1 and 2", "approve 1,2", "approve the roofing one", "approve"]
)
def test_anything_but_one_number_is_ambiguous(text):
    assert parse_command(text).verb == "ambiguous"


@pytest.mark.parametrize(
    "text",
    ["yes", "ok", "LGTM", "looks good to me", "send it", "ship it!", "\U0001f44d", "approved"],
)
def test_approval_like_messages_are_not_approvals(text):
    assert parse_command(text).verb == "approval_like"


def test_reject_reason_and_edit_text():
    assert parse_command("reject 2: too long").text == "too long"
    e = parse_command("edit 5: Hello\nthere")
    assert (e.verb, e.item_id, e.text) == ("edit", 5, "Hello\nthere")
    assert parse_command("edit 5 v3: x").version == 3


def test_misc():
    assert parse_command("list").verb == "list"
    assert parse_command("help").verb == "help"
    assert parse_command("lesson: never say 'synergy'").text == "never say 'synergy'"
    assert parse_command("what's for lunch").verb == "unknown"
    assert parse_command("approved by me 3").verb == "unknown"
