from human_approved_agents.approval.cli import run_cli
from human_approved_agents.cli import main
from human_approved_agents.demo import main as demo_main
from human_approved_agents.models import State


def test_scripted_cli_session(make_orch):
    o = make_orch()
    out: list[str] = []
    run_cli(
        o,
        "owner-1",
        lines=[
            "approve 1",
            "edit 3: Hi Priya,\\n\\nToo short.\\n\\nSam Rivera",
            "tick",
            "quit",
            "approve 2",
        ],
        out=out.append,
    )
    text = "\n".join(out)
    assert "Approved #1 v1." in text
    assert "#1 v1: DRY RUN, not sent" in text
    assert "#3 v2" in text
    assert "BLOCKED" in text
    assert o.store.get(3).current.text == "Hi Priya,\n\nToo short.\n\nSam Rivera"
    assert o.store.get(2).state is State.AWAITING_APPROVAL  # after quit


def test_demo_runs_end_to_end(capsys, tmp_path):
    assert demo_main(["--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    for expected in (
        "Reviewer blocked #1 v1",
        "You are not on the approver list",
        "That is not an approval",
        "is not the current version (v2)",
        "Voice approvals must say the version",
        "DRY RUN, not sent",
        "Silence is not approval",
        "audit chain intact",
    ):
        assert expected in out
    assert (tmp_path / "audit.jsonl").exists()


def test_cli_entrypoints(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path.parent)
    assert main(["verify-audit"]) == 0
    assert "no audit log yet" in capsys.readouterr().out
    monkeypatch.setenv("SEND_ENABLED", "maybe")
    assert main(["verify-audit"]) == 2
