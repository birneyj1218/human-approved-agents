"""Append-only JSONL audit log with a hash chain.

Every state transition, approval, denial and send is one line. Each line
carries the hash of the previous line, so an edited or deleted line breaks
``verify()``. This is tamper-evident, not tamper-proof: ship the file to
write-once storage if you need the latter.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .clock import Clock, utcnow

GENESIS = "0" * 64


def _digest(record: dict[str, Any]) -> str:
    body = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path, clock: Clock = utcnow) -> None:
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._last = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def record(
        self, event: str, *, actor: str, item_id: int | None = None, **detail: Any
    ) -> dict[str, Any]:
        with self._lock:
            entry: dict[str, Any] = {
                "ts": self.clock().isoformat(),
                "event": event,
                "actor": actor,
                "item_id": item_id,
                **detail,
                "prev": self._last,
            }
            entry["hash"] = _digest(entry)
            # "a" mode: we only ever append.
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
            self._last = entry["hash"]
            return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


def verify(path: Path) -> tuple[bool, str]:
    """Check the hash chain. Returns (ok, message)."""
    prev = GENESIS
    if not path.exists():
        return True, "no audit log yet"
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            entry = json.loads(line)
            claimed = entry.pop("hash", None)
            if entry.get("prev") != prev:
                return False, f"line {n}: chain broken (prev hash mismatch)"
            if _digest(entry) != claimed:
                return False, f"line {n}: content does not match its hash"
            prev = claimed
    return True, "audit chain intact"
