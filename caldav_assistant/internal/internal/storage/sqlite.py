"""SQLite repositories for Assistant local auxiliary state.

SQLite is local cache/auxiliary storage only.  It is not a Task/Event source of
truth.  Business rules belong in Core services, not in this module.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...api import Activity


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
            # Compatibility for any journal rows created by the original scaffold,
            # whose ActivityService used naive datetime.now().
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
                    json.dumps(
                        metadata or {},
                        ensure_ascii=False,
                        default=str,
                    ),
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
        """Compatibility helper for internal callers predating ActivityService v1.

        Public code should call ActivityService.today(), which owns the local-day
        semantics.  Keeping this method avoids breaking any scaffold-only caller.
        """
        now = datetime.now(timezone.utc).astimezone()
        start = datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)
        from datetime import timedelta

        end = start + timedelta(days=1)
        return self.between(
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
        )


class SQLiteOutboxRepository:
    def __init__(self, store):
        self.store = store
        store.migrate()

    def enqueue(self, payload):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO outbox(payload) VALUES(?)",
                (json.dumps(payload, default=str),),
            )

    def pending(self):
        return []


class SQLiteUndoRepository:
    def __init__(self, store):
        self.store = store
        store.migrate()

    def remember(self, payload):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO undo(payload) VALUES(?)",
                (json.dumps(payload, default=str),),
            )
