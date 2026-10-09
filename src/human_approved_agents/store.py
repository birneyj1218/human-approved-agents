"""SQLite persistence for items, versions, decisions and lessons."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import Issue, Item, Lead, Review, State, Version

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile TEXT NOT NULL,
    source_id TEXT NOT NULL,
    lead_json TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    redrafts INTEGER NOT NULL DEFAULT 0,
    approved_version INTEGER,
    approved_hash TEXT,
    approved_by TEXT,
    UNIQUE (profile, source_id)
);
CREATE TABLE IF NOT EXISTS versions (
    item_id INTEGER NOT NULL REFERENCES items(id),
    number INTEGER NOT NULL,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    review_json TEXT,
    PRIMARY KEY (item_id, number)
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    decision TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile TEXT,               -- NULL means every profile
    kind TEXT NOT NULL,         -- edit | reject | rule
    text TEXT NOT NULL,
    banned_phrase TEXT,         -- set for "never say X" rules
    item_id INTEGER,
    at TEXT NOT NULL
);
"""


def _review_to_json(review: Review | None) -> str | None:
    if review is None:
        return None
    return json.dumps(
        {
            "word_count": review.word_count,
            "issues": [
                {"rule": i.rule, "message": i.message, "blocking": i.blocking}
                for i in review.issues
            ],
        }
    )


def _review_from_json(raw: str | None) -> Review | None:
    if raw is None:
        return None
    d = json.loads(raw)
    return Review(
        issues=tuple(Issue(**i) for i in d["issues"]),
        word_count=d["word_count"],
    )


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL + NORMAL: durable across app crashes, far fewer fsyncs than the default.
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    # items ---------------------------------------------------------------
    def add_item(self, lead: Lead, now: datetime) -> Item | None:
        """Insert a new item; returns None if this lead was already seen."""
        with self.lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO items (profile, source_id, lead_json, state, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    lead.profile,
                    lead.source_id,
                    json.dumps(lead.__dict__),
                    State.NEW.value,
                    now.isoformat(),
                ),
            )
            if cur.rowcount == 0:
                return None
            assert cur.lastrowid is not None
            return self.get(cur.lastrowid)

    def get(self, item_id: int) -> Item | None:
        with self.lock:
            row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return None
            vrows = self._conn.execute(
                "SELECT * FROM versions WHERE item_id = ? ORDER BY number", (item_id,)
            ).fetchall()
        versions = [
            Version(
                number=v["number"],
                text=v["text"],
                author=v["author"],
                created_at=datetime.fromisoformat(v["created_at"]),
                review=_review_from_json(v["review_json"]),
            )
            for v in vrows
        ]
        return Item(
            id=row["id"],
            lead=Lead(**json.loads(row["lead_json"])),
            state=State(row["state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            versions=versions,
            redrafts=row["redrafts"],
            approved_version=row["approved_version"],
            approved_hash=row["approved_hash"],
            approved_by=row["approved_by"],
        )

    def ids_in_state(self, *states: State) -> list[int]:
        marks = ",".join("?" for _ in states)
        with self.lock:
            rows = self._conn.execute(
                f"SELECT id FROM items WHERE state IN ({marks}) ORDER BY id",  # noqa: S608
                [s.value for s in states],
            ).fetchall()
        return [r["id"] for r in rows]

    def save_state(self, item: Item) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "UPDATE items SET state = ?, redrafts = ?, approved_version = ?,"
                " approved_hash = ?, approved_by = ? WHERE id = ?",
                (
                    item.state.value,
                    item.redrafts,
                    item.approved_version,
                    item.approved_hash,
                    item.approved_by,
                    item.id,
                ),
            )

    def add_version(self, item_id: int, version: Version) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "INSERT INTO versions (item_id, number, text, author, created_at, review_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    version.number,
                    version.text,
                    version.author,
                    version.created_at.isoformat(),
                    _review_to_json(version.review),
                ),
            )

    def set_review(self, item_id: int, number: int, review: Review) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "UPDATE versions SET review_json = ? WHERE item_id = ? AND number = ?",
                (_review_to_json(review), item_id, number),
            )

    # decisions and lessons -------------------------------------------------
    def add_decision(
        self, item_id: int, version: int, decision: str, actor: str, reason: str, now: datetime
    ) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "INSERT INTO decisions (item_id, version, decision, actor, reason, at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, version, decision, actor, reason, now.isoformat()),
            )

    def decisions(self, item_id: int) -> list[sqlite3.Row]:
        with self.lock:
            return self._conn.execute(
                "SELECT * FROM decisions WHERE item_id = ? ORDER BY id", (item_id,)
            ).fetchall()

    def add_lesson(
        self,
        *,
        profile: str | None,
        kind: str,
        text: str,
        now: datetime,
        banned_phrase: str | None = None,
        item_id: int | None = None,
    ) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "INSERT INTO lessons (profile, kind, text, banned_phrase, item_id, at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (profile, kind, text, banned_phrase, item_id, now.isoformat()),
            )

    def lessons(self, profile: str, limit: int) -> list[sqlite3.Row]:
        with self.lock:
            return self._conn.execute(
                "SELECT * FROM lessons WHERE profile IS NULL OR profile = ?"
                " ORDER BY id DESC LIMIT ?",
                (profile, limit),
            ).fetchall()

    def banned_phrases(self, profile: str) -> list[str]:
        with self.lock:
            rows = self._conn.execute(
                "SELECT banned_phrase FROM lessons WHERE banned_phrase IS NOT NULL"
                " AND (profile IS NULL OR profile = ?)",
                (profile,),
            ).fetchall()
        return [r["banned_phrase"] for r in rows]
