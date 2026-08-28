"""SQLite repositories for Assistant local auxiliary state.

SQLite is local cache/auxiliary storage only.  It is not a Task/Event source of
truth.  Business rules belong in Core services, not in this module.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ...api import Activity
from .outbox import SQLiteOutboxRepository


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.path)

    def migrate(self) -> None:
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS kv ("
                "namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
                "PRIMARY KEY(namespace,key))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS activity ("
                "timestamp TEXT NOT NULL, action TEXT NOT NULL, "
                "object_id TEXT, metadata TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS outbox ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS undo ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_timestamp "
                "ON activity(timestamp)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_object_id "
                "ON activity(object_id)"
            )


class SQLiteKeyValueRepository:
    def __init__(self, store: SQLiteStore, namespace: str):
        self.store = store
        self.namespace = namespace
        store.migrate()

    def get(self, key: str, default: Any = None):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT value FROM kv WHERE namespace=? AND key=?",
                (self.namespace, key),
            ).fetchone()
        return default if row is None else json.loads(row[0])

    def set(self, key: str, value: Any):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO kv(namespace,key,value) VALUES(?,?,?) "
                "ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value",
                (
                    self.namespace,
                    key,
                    json.dumps(value, ensure_ascii=False, default=str),
                ),
            )

    def delete(self, key: str):
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM kv WHERE namespace=? AND key=?",
                (self.namespace, key),
            )


class SQLiteCacheRepository(SQLiteKeyValueRepository):
    def __init__(self, store):
        super().__init__(store, "cache")


class SQLiteActivityRepository:
    """Persistence-only repository for Activity Journal rows."""

    def __init__(self, store: SQLiteStore):
        self.store = store
        store.migrate()

    @staticmethod
    def _timestamp_text(value: datetime) -> str:
        if not isinstance(value, datetime):
            raise TypeError("activity timestamp must be datetime")
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode(row: tuple[str, str, str | None, str]) -> Activity:
        timestamp_text, action, object_id, metadata_text = row
        timestamp = datetime.fromisoformat(timestamp_text)
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
        timestamp = timestamp.astimezone(timezone.utc)

        metadata = json.loads(metadata_text or "{}")
        if not isinstance(metadata, dict):
            metadata = {"value": metadata}

        return Activity(
            timestamp=timestamp,
            action=action,
            object_id=object_id,
            metadata=metadata,
        )

    def record(
        self,
        timestamp: datetime,
        action: str,
        object_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO activity(timestamp,action,object_id,metadata) "
                "VALUES(?,?,?,?)",
                (
                    self._timestamp_text(timestamp),
                    action,
                    object_id,
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                ),
            )

    def between(self, start: datetime, end: datetime) -> list[Activity]:
        start_text = self._timestamp_text(start)
        end_text = self._timestamp_text(end)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT timestamp,action,object_id,metadata "
                "FROM activity WHERE timestamp>=? AND timestamp<? "
                "ORDER BY timestamp ASC, rowid ASC",
                (start_text, end_text),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def for_object(self, object_id: str) -> list[Activity]:
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT timestamp,action,object_id,metadata "
                "FROM activity WHERE object_id=? "
                "ORDER BY timestamp ASC, rowid ASC",
                (object_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def today(self) -> list[Activity]:
        now = datetime.now(timezone.utc).astimezone()
        start = datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)
        from datetime import timedelta

        end = start + timedelta(days=1)
        return self.between(
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
        )


_UNDO_TYPE = "__caldav_assistant_type__"


def _undo_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return {_UNDO_TYPE: "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {_UNDO_TYPE: "date", "value": value.isoformat()}
    raise TypeError(f"Unsupported undo value: {type(value).__name__}")


def _undo_object_hook(value: dict[str, Any]) -> Any:
    kind = value.get(_UNDO_TYPE)
    raw = value.get("value")
    if kind == "datetime" and isinstance(raw, str):
        return datetime.fromisoformat(raw)
    if kind == "date" and isinstance(raw, str):
        return date.fromisoformat(raw)
    return value


class SQLiteUndoRepository:
    """Durable LIFO undo journal preserving temporal Python types."""

    def __init__(self, store):
        self.store = store
        store.migrate()

    def remember(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            default=_undo_default,
            separators=(",", ":"),
        )
        with self.store.connect() as db:
            db.execute("INSERT INTO undo(payload) VALUES(?)", (encoded,))

    def latest(self) -> dict[str, Any] | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,payload,created_at FROM undo ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        item_id, payload_text, created_at = row
        payload = json.loads(payload_text, object_hook=_undo_object_hook)
        if not isinstance(payload, dict):
            raise ValueError("Malformed undo payload")
        return {"id": int(item_id), "payload": payload, "created_at": created_at}

    def discard(self, item_id: int) -> None:
        with self.store.connect() as db:
            db.execute("DELETE FROM undo WHERE id=?", (int(item_id),))


__all__ = [
    "SQLiteStore",
    "SQLiteKeyValueRepository",
    "SQLiteCacheRepository",
    "SQLiteActivityRepository",
    "SQLiteOutboxRepository",
    "SQLiteUndoRepository",
]
