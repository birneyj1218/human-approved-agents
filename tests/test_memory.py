from datetime import UTC, datetime

from human_approved_agents.memory import Memory, lessons_from_edit, parse_never_say, sentences
from human_approved_agents.store import Store

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_shortening_is_learned():
    before = " ".join(["word"] * 100) + "."
    after = " ".join(["word"] * 50) + "."
    assert lessons_from_edit(before, after, "Jo")[0] == (
        "Jo shortened a draft from 100 to 50 words; aim for about 50."
    )
    assert "lengthened" in lessons_from_edit(after, before, "Jo")[0]


def test_removed_sentences_are_learned_but_merges_and_greetings_are_not():
    before = "Hi Sam,\n\nI build bots. I love synergy. I test things.\n\nBest,"
    after = "Hi Alex,\n\nI build bots, and I test things.\n\nBest,"
    lessons = lessons_from_edit(before, after, "Jo")
    assert lessons == ['Jo removed the sentence: "I love synergy."']


def test_long_removed_sentence_is_truncated():
    before = "Keep this one please. " + "Long " * 40 + "end."
    lesson = lessons_from_edit(before, "Keep this one please.", "Jo")[-1]
    assert lesson.endswith('..."')
    assert len(lesson) < 130


def test_never_say_parsing():
    assert parse_never_say('never say "circle back"') == "circle back"
    assert parse_never_say("Don't use synergy.") == "synergy"
    assert parse_never_say("do not write ‘ASAP’") == "ASAP"
    assert parse_never_say("keep it short") is None


def test_sentences_split_on_lines_and_punctuation():
    assert sentences("A b.  C d!\nE f") == ["A b.", "C d!", "E f"]


def test_memory_roundtrip_and_scoping():
    m = Memory(Store(":memory:"), owner_name="Jo", limit=3)
    m.record_rule("never say 'cheap'", NOW)
    m.record_rule("keep replies warm", NOW, profile="roof")
    assert m.record_rejection(profile="roof", item_id=1, reason="  ", now=NOW) is None
    m.record_rejection(profile="roof", item_id=1, reason="too pushy", now=NOW)
    m.record_edit(
        profile="other",
        item_id=2,
        before="A long one. This part is gone now.",
        after="A long one.",
        now=NOW,
    )
    assert m.lessons_for("roof") == [
        "Jo's rule: never say 'cheap'",
        "Jo's rule: keep replies warm",
        "Jo rejected a draft because: too pushy",
    ]
    assert m.banned_phrases("roof") == ["cheap"]
    assert m.banned_phrases("other") == ["cheap"]
    assert any("gone now" in s for s in m.lessons_for("other"))
