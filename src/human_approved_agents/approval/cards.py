"""How an item looks when it is posted for approval."""

from __future__ import annotations

from ..models import Item

HELP = (
    "Commands: approve N | approve N vK | reject N <reason> | edit N: <new text> | "
    "show N | list | lesson: <rule>. Silence is never approval."
)


def render_card(item: Item) -> str:
    v = item.current
    assert v is not None
    review = v.review
    who = item.lead.contact_name or "unknown"
    lines = [
        f'#{item.id} v{v.number} | {item.lead.profile} | reply to {who} re "{item.lead.title}"'
    ]
    if v.author.startswith("human:"):
        lines.append("Written by: you (edited version)")
    if review is not None:
        status = "PASS" if review.passed else "BLOCKED"
        lines.append(f"Review: {status} ({review.word_count} words)")
        for issue in review.issues:
            tag = "must fix" if issue.blocking else "note"
            lines.append(f"  - [{tag}] {issue.message}")
    lines += ["-----", v.text, "-----"]
    if review is not None and not review.passed:
        lines.append(
            f"Cannot be approved as is. Reply: edit {item.id}: <text>  or  reject {item.id}"
        )
    else:
        lines.append(
            f"Reply: approve {item.id}  |  edit {item.id}: <text>  |  reject {item.id} <reason>"
        )
    return "\n".join(lines)


def render_summary(items: list[Item]) -> str:
    if not items:
        return "Nothing is waiting for approval."
    rows = [f"#{i.id} v{i.current.number if i.current else 0} {i.lead.title}" for i in items]
    return "Waiting for approval:\n" + "\n".join(rows)
