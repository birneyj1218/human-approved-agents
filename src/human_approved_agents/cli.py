"""Command line: ``haa demo | run | verify-audit | lessons``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .app import build
from .audit import verify
from .config import ConfigError, Settings


def _voice(settings: Settings):  # type: ignore[no-untyped-def]
    """Return (transcriber, speaker) or (None, None) if voice is off or unavailable."""
    if not settings.voice_enabled:
        return None, None
    from .voice import Speaker, Transcriber, choose_device

    device = choose_device(settings.voice_device)
    if device is None:
        return None, None
    logging.getLogger(__name__).info("voice on (%s)", device)
    speaker = Speaker(settings.piper_voice_path) if settings.piper_voice_path else None
    return Transcriber(settings.whisper_model, device), speaker


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="haa")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run the scripted end-to-end demo (offline)")
    run_p = sub.add_parser("run", help="run the loop with an approval channel")
    run_p.add_argument("--adapter", choices=["cli", "discord"], default="cli")
    run_p.add_argument("--poll-seconds", type=float, default=60)
    sub.add_parser("verify-audit", help="check the audit log hash chain")
    les = sub.add_parser("lessons", help="print the lessons for a profile")
    les.add_argument("profile")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.cmd == "demo":
        from .demo import main as demo_main

        return demo_main([])

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "verify-audit":
        ok, msg = verify(settings.audit_path)
        print(msg)
        return 0 if ok else 1

    orch = build(settings)
    if args.cmd == "lessons":
        for lesson in orch.memory.lessons_for(args.profile):
            print(f"- {lesson}")
        return 0

    try:
        settings.require_approvers()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    print(f"SEND_ENABLED={settings.send_enabled} (false means dry run: nothing is delivered)")

    if args.adapter == "cli":
        from .approval.cli import run_cli

        if settings.cli_user_id not in settings.approver_ids:
            print("note: CLI_USER_ID is not in APPROVER_USER_IDS, so commands will be refused")
        run_cli(orch, settings.cli_user_id)
        return 0

    if not settings.discord_token or not settings.discord_channel_id:
        print("config error: set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID", file=sys.stderr)
        return 2
    from .approval.discord_bot import DiscordApprover

    transcriber, speaker = _voice(settings)
    DiscordApprover(
        orch,
        channel_id=settings.discord_channel_id,
        approvers=settings.approver_ids,
        poll_seconds=args.poll_seconds,
        transcriber=transcriber,
        speaker=speaker,
    ).run(settings.discord_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
