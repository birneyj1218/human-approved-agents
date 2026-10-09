import io
import json

from human_approved_agents.cli import main
from human_approved_agents.models import Lead
from human_approved_agents.senders import ConsoleSender, FileSender

LEAD = Lead("p", "id-1", "t", "b", "Dana", "dana@example.com")


def test_console_sender():
    buf = io.StringIO()
    assert ConsoleSender(buf).send(LEAD, "Hello") == "console:id-1"
    assert "SENT to dana@example.com" in buf.getvalue()


def test_file_sender_appends_jsonl(tmp_path):
    s = FileSender(tmp_path / "out" / "outbox.jsonl")
    s.send(LEAD, "one")
    s.send(LEAD, "two")
    rows = [json.loads(x) for x in (tmp_path / "out" / "outbox.jsonl").read_text().splitlines()]
    assert [r["text"] for r in rows] == ["one", "two"]
    assert rows[0]["to"] == "dana@example.com"


def test_run_refuses_without_approvers(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path.parent)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PROFILES_DIR", str(root / "profiles"))
    monkeypatch.setenv("FIXTURES_DIR", str(root / "fixtures"))
    monkeypatch.delenv("APPROVER_USER_IDS", raising=False)
    assert main(["run"]) == 2
    assert "nobody could approve" in capsys.readouterr().err
    monkeypatch.setenv("APPROVER_USER_IDS", "123")
    assert main(["run", "--adapter", "discord"]) == 2
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().err
    assert main(["lessons", "freelancer"]) == 0
