from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any

class SQLiteStore:
    def __init__(self, path: str | Path): self.path = Path(path)
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.path)
    def migrate(self):
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS kv (namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY(namespace,key))")
            db.execute("CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT, metadata TEXT NOT NULL DEFAULT '{}')")
            db.execute("CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS undo (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

class SQLiteKeyValueRepository:
    def __init__(self, store: SQLiteStore, namespace: str): self.store=store; self.namespace=namespace; store.migrate()
    def get(self, key: str, default: Any=None):
        with self.store.connect() as db:
            row=db.execute("SELECT value FROM kv WHERE namespace=? AND key=?",(self.namespace,key)).fetchone()
        return default if row is None else json.loads(row[0])
    def set(self, key: str, value: Any):
        with self.store.connect() as db:
            db.execute("INSERT INTO kv(namespace,key,value) VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value",(self.namespace,key,json.dumps(value, ensure_ascii=False, default=str)))
    def delete(self, key: str):
        with self.store.connect() as db: db.execute("DELETE FROM kv WHERE namespace=? AND key=?",(self.namespace,key))

class SQLiteCacheRepository(SQLiteKeyValueRepository):
    def __init__(self, store): super().__init__(store, 'cache')
class SQLiteActivityRepository:
    def __init__(self, store): self.store=store; store.migrate()
    def record(self, timestamp, action, object_id=None, metadata=None):
        with self.store.connect() as db: db.execute("INSERT INTO activity(timestamp,action,object_id,metadata) VALUES(?,?,?,?)",(str(timestamp),action,object_id,json.dumps(metadata or {},ensure_ascii=False,default=str)))
    def today(self): return []
class SQLiteOutboxRepository:
    def __init__(self, store): self.store=store; store.migrate()
    def enqueue(self, payload):
        with self.store.connect() as db: db.execute("INSERT INTO outbox(payload) VALUES(?)",(json.dumps(payload,default=str),))
    def pending(self): return []
class SQLiteUndoRepository:
    def __init__(self, store): self.store=store; store.migrate()
    def remember(self, payload):
        with self.store.connect() as db: db.execute("INSERT INTO undo(payload) VALUES(?)",(json.dumps(payload,default=str),))
