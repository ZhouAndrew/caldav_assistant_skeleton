from __future__ import annotations

import sqlite3

from caldav_assistant.internal.storage.outbox import SQLiteOutboxRepository


class Store:
    def __init__(self, path):
        self.path = path

    def connect(self):
        return sqlite3.connect(self.path)

    def migrate(self):
        with self.connect() as db:
            # Old scaffold schema: prove the new repository migrates it in place.
            db.execute(
                "CREATE TABLE IF NOT EXISTS outbox ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "payload TEXT NOT NULL,"
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )


def test_outbox_preserves_fifo_rows_and_retry_metadata(tmp_path):
    repo = SQLiteOutboxRepository(Store(tmp_path / "state.sqlite3"))

    one = repo.enqueue({"operation": "create_log", "args": {"text": "A"}})
    two = repo.enqueue({"operation": "create_log", "args": {"text": "B"}})

    assert [item["id"] for item in repo.pending()] == [one["id"], two["id"]]
    assert repo.pending(limit=1)[0]["payload"]["args"]["text"] == "A"

    repo.mark_failed(one["id"], RuntimeError("offline"))
    failed = repo.pending()[0]
    assert failed["attempts"] == 1
    assert failed["last_error"] == "offline"

    repo.mark_sent(one["id"])
    assert [item["id"] for item in repo.pending()] == [two["id"]]
