from conftest import OWNER
from human_approved_agents.llm import FakeLLM
from human_approved_agents.models import State

GOOD_ROOF = (
    "Hi Dana,\n\nSorry about the leak. Free inspections are booked Monday to Friday, 8 am to 5 pm, "
    "and for an active leak we can place a temporary tarp, usually within 48 hours of the "
    "inspection.\n\nThe Blue Gable Roofing team"
)
BAD_ROOF = (
    "Hi Dana,\n\nI hope this email finds you well. We have 30 years of experience and offer "
    "same-day repairs on every roof in town, so you are in good hands with us.\n\n"
    "The Blue Gable Roofing team"
)


def test_researcher_items_flow_to_cards(make_orch):
    o = make_orch()
    messages = o.tick()
    assert len(messages) == 5
    assert all(m.startswith("#") for m in messages)
    events = [e["event"] for e in o.audit.entries()]
    assert events.count("created") == 5


def test_ingest_is_idempotent(make_orch):
    o = make_orch()
    o.tick()
    assert o.ingest() == 0
    assert o.tick() == []


def test_reviewer_failure_triggers_redraft_with_feedback(make_orch):
    llm = FakeLLM(script=[BAD_ROOF, GOOD_ROOF] + [GOOD_ROOF] * 10)
    o = make_orch(llm=llm)
    o.tick()
    item = o.store.get(1)
    assert [v.number for v in item.versions] == [1, 2]
    assert not item.versions[0].review.passed
    assert item.versions[1].review.passed
    assert item.redrafts == 1
    feedback_prompt = llm.calls[1][-1]["content"]
    assert "rejected by the reviewer" in feedback_prompt
    assert "30" in feedback_prompt
    assert "same-day" in feedback_prompt


def test_redrafts_are_capped_and_blocked_item_is_shown_not_sent(make_orch, sender):
    o = make_orch(llm=FakeLLM(script=[BAD_ROOF] * 3 + [GOOD_ROOF] * 10), max_redrafts=2)
    cards = o.tick()
    item = o.store.get(1)
    assert len(item.versions) == 3
    assert item.state is State.AWAITING_APPROVAL
    assert "BLOCKED" in cards[0]
    assert "blocking review issues" in o.handle_command(OWNER, "approve 1")[0]
    assert sender.sent == []


def test_llm_error_leaves_item_new_and_retries_next_tick(make_orch):
    llm = FakeLLM(script=[])
    o = make_orch(llm=llm)
    assert o.tick() == []
    assert o.store.get(1).state is State.NEW
    assert any(e["event"] == "draft_error" for e in o.audit.entries())
    llm.script = None  # model is back
    assert len(o.tick()) == 5


def test_llm_error_during_redraft_keeps_item_reviewed(make_orch):
    o = make_orch(llm=FakeLLM(script=[BAD_ROOF]))
    o.tick()
    assert o.store.get(1).state is State.REVIEWED


def test_lessons_reach_the_drafter_prompt(make_orch):
    llm = FakeLLM()
    o = make_orch(llm=llm)
    o.memory.record_rule('never say "circle back"', o.clock())
    o.tick()
    system = llm.calls[0][0]["content"]
    assert 'Owner\'s rule: never say "circle back"' in system
    assert '"circle back"' in system.split("Never use these phrases:")[1].splitlines()[0]


def test_unknown_profile_leads_are_ignored(make_orch):
    o = make_orch()
    o.profiles.pop("freelancer")
    o.tick()
    assert len(o.store.ids_in_state(*State)) == 2


def test_dry_run_marks_sent_without_calling_sender(orch, sender):
    orch.handle_command(OWNER, "approve 1")
    notes = orch.deliver().notes
    assert notes == ["#1 v1: DRY RUN, not sent (dry-run: would send via recording)."]
    assert sender.sent == []
    assert orch.store.get(1).state is State.SENT
    last = orch.audit.entries()[-1]
    assert (last["to"], last["mode"], last["approved_by"]) == ("sent", "dry_run", f"human:{OWNER}")


def test_live_send_sends_exactly_once(make_orch, sender):
    o = make_orch(send_enabled=True)
    o.tick()
    o.handle_command(OWNER, "approve 1")
    o.deliver()
    o.deliver()
    o.tick()
    assert len(sender.sent) == 1
    assert sender.sent[0][1] == o.store.get(1).versions[0].text


def test_send_rate_limit_defers_not_drops(make_orch, sender, clock):
    o = make_orch(send_enabled=True, max_sends_per_hour=1)
    o.tick()
    o.handle_command(OWNER, "approve 1")
    o.handle_command(OWNER, "approve 2")
    notes = o.deliver().notes
    assert len(sender.sent) == 1
    assert "hourly send limit" in notes[1]
    assert o.store.get(2).state is State.APPROVED
    clock.advance(hours=1)
    o.deliver()
    assert len(sender.sent) == 2


def test_tampered_text_after_approval_is_refused(make_orch, sender):
    o = make_orch(send_enabled=True)
    o.tick()
    o.handle_command(OWNER, "approve 1")
    # Simulate someone changing the stored text after approval.
    o.store._conn.execute("UPDATE versions SET text = 'Pay me now' WHERE item_id = 1")
    notes = o.deliver().notes
    assert "does not match what was approved" in notes[0]
    assert sender.sent == []
    assert o.store.get(1).state is State.APPROVED
