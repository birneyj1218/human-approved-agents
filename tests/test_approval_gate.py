"""The approval rules. These are the tests that matter most."""

from conftest import GOOD_EDIT, OWNER, STRANGER, awaiting_ids
from human_approved_agents.llm import FakeLLM
from human_approved_agents.models import State, content_hash


def test_all_items_wait_for_a_human(orch, sender):
    assert awaiting_ids(orch) == [1, 2, 3, 4, 5]
    orch.tick()
    orch.tick()
    assert sender.sent == []
    assert awaiting_ids(orch) == [1, 2, 3, 4, 5]


def test_silence_is_not_approval(orch, clock, sender):
    clock.advance(days=30)
    orch.tick()
    assert all(orch.store.get(i).state is State.AWAITING_APPROVAL for i in range(1, 6))
    assert sender.sent == []


def test_approve_records_exact_version_and_hash(orch):
    replies = orch.handle_command(OWNER, "approve 2")
    assert replies == ["Approved #2 v1."]
    item = orch.store.get(2)
    assert item.state is State.APPROVED
    assert item.approved_version == 1
    assert item.approved_hash == content_hash(item.versions[0].text)
    assert item.approved_by == f"human:{OWNER}"
    assert [d["decision"] for d in orch.store.decisions(2)] == ["approved"]


def test_approval_covers_only_that_item(orch):
    orch.handle_command(OWNER, "approve 2")
    assert [orch.store.get(i).state for i in (1, 3, 4, 5)] == [State.AWAITING_APPROVAL] * 4


def test_wrong_user_cannot_approve_reject_edit_or_teach(orch):
    for cmd in ("approve 1", "reject 1 no", f"edit 1: {GOOD_EDIT}", "lesson: never say hi"):
        replies = orch.handle_command(STRANGER, cmd)
        assert replies == ["You are not on the approver list. Nothing was changed."]
    assert orch.store.get(1).state is State.AWAITING_APPROVAL
    assert len(orch.store.get(1).versions) == 1
    assert orch.memory.lessons_for("blue-gable-roofing") == []
    denied = [e for e in orch.audit.entries() if e["event"] == "denied"]
    assert len(denied) == 4
    assert all(e["actor"] == f"human:{STRANGER}" for e in denied)


def test_display_name_spoofing_does_not_matter(orch):
    # Identity is the user ID string, never a name typed in the message.
    assert "not on the approver list" in orch.handle_command("Owner", "approve 1")[0]


def test_double_approve_is_a_no_op(orch, sender):
    orch.handle_command(OWNER, "approve 1")
    before = len(orch.audit.entries())
    assert orch.handle_command(OWNER, "approve 1") == ["#1 v1 is already approved. Nothing to do."]
    assert len(orch.audit.entries()) == before
    orch.deliver()
    assert orch.handle_command(OWNER, "approve 1") == ["#1 v1 is already approved. Nothing to do."]
    orch.deliver()
    assert len(sender.sent) == 0  # dry run by default; see delivery tests for live sends


def test_rejected_item_cannot_be_approved_or_edited(orch):
    assert orch.handle_command(OWNER, "reject 3 too generic") == [
        "Rejected #3. It will not be sent."
    ]
    assert "was rejected" in orch.handle_command(OWNER, "approve 3")[0]
    assert "was rejected" in orch.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")[0]
    assert orch.store.get(3).state is State.REJECTED
    orch.deliver()
    assert orch.store.get(3).state is State.REJECTED


def test_edit_creates_new_version_needing_fresh_approval(orch):
    replies = orch.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")
    assert replies[0].startswith("Saved your edit as #3 v2")
    assert replies[1].startswith("#3 v2 | freelancer")  # new card, reviewed again
    item = orch.store.get(3)
    assert item.state is State.AWAITING_APPROVAL
    assert item.current.number == 2
    assert item.current.author == f"human:{OWNER}"
    assert item.current.review is not None
    assert item.current.review.passed
    assert item.approved_version is None


def test_approval_of_old_version_is_refused_after_edit(orch):
    orch.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")
    assert orch.handle_command(OWNER, "approve 3 v1") == [
        "#3 v1 is not the current version (v2). Nothing was approved."
    ]
    assert orch.store.get(3).state is State.AWAITING_APPROVAL
    assert any(e["event"] == "stale_approval_refused" for e in orch.audit.entries())
    assert orch.handle_command(OWNER, "approve 3 v2") == ["Approved #3 v2."]


def test_sent_text_is_the_edited_version(make_orch, sender):
    o = make_orch(send_enabled=True)
    o.tick()
    o.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")
    o.handle_command(OWNER, "approve 3")
    o.deliver()
    assert sender.sent == [("jobs.example.com/1001", GOOD_EDIT)]


def test_edit_that_fails_review_cannot_be_approved(orch):
    bad = "Hi Priya, I have 15 years of experience. Sam Rivera"
    replies = orch.handle_command(OWNER, f"edit 3: {bad}")
    assert "BLOCKED" in replies[1]
    assert "Cannot be approved as is" in replies[1]
    assert "blocking review issues" in orch.handle_command(OWNER, "approve 3")[0]
    assert orch.store.get(3).state is State.AWAITING_APPROVAL
    # The human can fix it with another edit.
    orch.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")
    assert orch.handle_command(OWNER, "approve 3") == ["Approved #3 v3."]


def test_human_edit_is_never_rewritten_by_the_drafter(orch):
    llm_calls = len(orch.drafter.llm.calls)
    orch.handle_command(OWNER, "edit 3: Hi Priya, I have 15 years of experience. Sam Rivera")
    assert len(orch.drafter.llm.calls) == llm_calls
    assert orch.store.get(3).current.author.startswith("human:")


def test_edit_against_stale_version_is_refused(orch):
    orch.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")
    reply = orch.handle_command(OWNER, f"edit 3 v1: {GOOD_EDIT} again")
    assert "your edit was for v1" in reply[0]


def test_edit_with_identical_text_changes_nothing(orch):
    text = orch.store.get(2).current.text
    assert "same as the current version" in orch.handle_command(OWNER, f"edit 2: {text}")[0]
    assert len(orch.store.get(2).versions) == 1


def test_ambiguous_and_approval_like_messages_change_nothing(orch):
    for msg in ("approve all", "approve 1 and 2", "looks good", "yes", "send it"):
        orch.handle_command(OWNER, msg)
    assert awaiting_ids(orch) == [1, 2, 3, 4, 5]


def test_unknown_item_and_unknown_text(orch):
    assert orch.handle_command(OWNER, "approve 99") == ["There is no item #99."]
    assert orch.handle_command(OWNER, "nice weather") == []
    assert orch.handle_command(STRANGER, "help")[0].startswith("Commands:")


def test_cannot_approve_item_still_in_review(make_orch):
    o = make_orch(llm=FakeLLM(script=[]))  # LLM fails: item stays NEW
    o.tick()
    assert o.store.get(1).state is State.NEW
    assert "still being drafted" in o.handle_command(OWNER, "approve 1")[0]


def test_voice_approval_must_name_the_version(orch):
    reply = orch.handle_command(OWNER, "approve 2", source="voice")
    assert "must say the version" in reply[0]
    assert orch.store.get(2).state is State.AWAITING_APPROVAL
    assert orch.handle_command(OWNER, "approve 2 v1", source="voice") == ["Approved #2 v1."]


def test_rate_limit_on_commands(make_orch, clock):
    o = make_orch(max_commands_per_minute=2)
    o.tick()
    o.handle_command(OWNER, "show 1")
    o.handle_command(OWNER, "show 2")
    assert "Too many commands" in o.handle_command(OWNER, "approve 1")[0]
    assert o.store.get(1).state is State.AWAITING_APPROVAL
    clock.advance(minutes=1)
    assert o.handle_command(OWNER, "approve 1") == ["Approved #1 v1."]


def test_show_and_list(orch):
    assert orch.handle_command(OWNER, "show 2")[0].startswith("#2 v1")
    listing = orch.handle_command(OWNER, "list")[0]
    assert listing.startswith("Waiting for approval:")
    assert "#5 v1" in listing
    for i in range(1, 6):
        orch.handle_command(OWNER, f"reject {i}")
    assert orch.handle_command(OWNER, "list") == ["Nothing is waiting for approval."]


def test_every_human_decision_is_audited_with_actor(orch):
    orch.handle_command(OWNER, "approve 1")
    orch.handle_command(OWNER, "reject 2 wrong tone")
    orch.handle_command(OWNER, f"edit 3: {GOOD_EDIT}")
    human = [
        e
        for e in orch.audit.entries()
        if e["event"] == "transition" and e["actor"] != "system" and e["actor"].startswith("human:")
    ]
    assert [(e["item_id"], e["to"]) for e in human] == [
        (1, "approved"),
        (2, "rejected"),
        (3, "edited"),
    ]
    assert human[0]["content_hash"] == orch.store.get(1).approved_hash
