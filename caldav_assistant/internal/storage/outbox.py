"""SQLite-backed durable WordPress Outbox repository.

MODULE CONTRACT
- Imports/calls: stdlib + injected SQLiteStore.connect()/migrate().
- Provides: SQLiteOutboxRepository.
- Must not: know WordPress transport semantics, Task/Event rules, CLI/UI, or retry
  scheduling policy.

The repository reuses the scaffold's existing ``outbox`` table and migrates it in
place by adding retry metadata columns.  Existing queued payload rows are preserved.
"""
from __future__ import annotations

import json
from typing import Any


class SQLiteOutboxRepository:
    """Durable FIFO queue with explicit acknowledge/failure operations."""

    def __init__(self, store: Any) -> None:
        self.store = store
        if hasattr(store, "migrate"):
            store.migrate()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.store.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(outbox)").fetchall()
            }
            if "attempts" not in columns:
                db.execute(
                    "ALTER TABLE outbox "
                    "ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "last_error" not in columns:
                db.execute("ALTER TABLE outbox ADD COLUMN last_error TEXT")

    @staticmethod
    def _item(row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row[1])
        except (TypeError, json.JSONDecodeError):
            payload = row[1]
        return {
            "id": int(row[0]),
            "payload": payload,
            "created_at": row[2],
            "attempts": int(row[3] or 0),
            "last_error": row[4],
        }

    @staticmethod
    def _validate_limit(limit: int | None) -> int | None:
        if limit is None:
            return None
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Outbox limit must be a positive integer")
        return limit

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("Outbox payload must be a dict")
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        with self.store.connect() as db:
            cursor = db.execute(
                "INSERT INTO outbox(payload) VALUES(?)",
                (encoded,),
            )
            item_id = int(cursor.lastrowid)
            row = db.execute(
                "SELECT id,payload,created_at,attempts,last_error "
                "FROM outbox WHERE id=?",
                (item_id,),
            ).fetchone()
        return self._item(row)

    def pending(self, limit: int | None = None) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)
        sql = (
            "SELECT id,payload,created_at,attempts,last_error "
            "FROM outbox ORDER BY id ASC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self.store.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._item(row) for row in rows]

    def mark_sent(self, item_id: int) -> None:
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
            raise ValueError("Outbox id must be a positive integer")
        with self.store.connect() as db:
            db.execute("DELETE FROM outbox WHERE id=?", (item_id,))

    def mark_failed(self, item_id: int, error: Any) -> None:
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
            raise ValueError("Outbox id must be a positive integer")
        text = str(error)[:2000]
        with self.store.connect() as db:
            db.execute(
                "UPDATE outbox "
                "SET attempts=attempts+1,last_error=? WHERE id=?",
                (text, item_id),
            )

    def count(self) -> int:
        with self.store.connect() as db:
            row = db.execute("SELECT COUNT(*) FROM outbox").fetchone()
        return int(row[0])
