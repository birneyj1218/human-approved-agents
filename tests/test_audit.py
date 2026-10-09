import json

from human_approved_agents.audit import AuditLog, verify


def test_chain_verifies_and_survives_reopen(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.record("created", actor="researcher", item_id=1)
    log.record("transition", actor="human:1", item_id=1, frm="awaiting_approval", to="approved")
    AuditLog(path).record("transition", actor="sender", item_id=1, to="sent")
    assert verify(path) == (True, "audit chain intact")
    assert [e["event"] for e in log.entries()] == ["created", "transition", "transition"]


def test_edited_line_is_detected(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.record("transition", actor="human:1", item_id=1, to="rejected")
    log.record("transition", actor="human:1", item_id=2, to="approved")
    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    first["to"] = "approved"
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    ok, msg = verify(path)
    assert not ok
    assert "line 1" in msg


def test_deleted_line_is_detected(tmp_path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    for i in range(3):
        log.record("x", actor="system", item_id=i)
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n" + lines[2] + "\n")
    ok, msg = verify(path)
    assert not ok
    assert "chain broken" in msg


def test_missing_log_is_ok(tmp_path):
    assert verify(tmp_path / "none.jsonl") == (True, "no audit log yet")
