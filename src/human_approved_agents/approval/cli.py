"""Terminal approval channel: same commands as Discord, typed at a prompt."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..orchestrator import Orchestrator

PROMPT_HELP = (
    "Type a command (approve N, edit N: text, reject N reason, show N, list, lesson: ...),\n"
    "'tick' to run the agents again, or 'quit'. Use \\n inside an edit for a line break."
)


def run_cli(
    orch: Orchestrator,
    user_id: str,
    *,
    lines: Iterable[str] | None = None,
    out: Callable[[str], None] = print,
) -> None:
    """Run the loop. ``lines`` defaults to stdin; pass a list to script it."""

    def show(messages: list[str]) -> None:
        for m in messages:
            out(m)
            out("")

    show(orch.tick())
    out(PROMPT_HELP)
    source = lines if lines is not None else _stdin_lines()
    for raw in source:
        line = raw.strip()
        if line in {"quit", "exit"}:
            break
        if line in {"", "tick"}:
            show(orch.tick())
            continue
        show(orch.handle_command(user_id, line.replace("\\n", "\n")))
        show(orch.deliver().messages())


def _stdin_lines() -> Iterable[str]:  # pragma: no cover - interactive
    while True:
        try:
            yield input("> ")
        except EOFError:
            return
