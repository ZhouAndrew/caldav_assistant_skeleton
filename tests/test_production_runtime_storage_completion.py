from __future__ import annotations

from caldav_assistant.internal.bootstrap import build_service_application
from caldav_assistant.internal.storage.outbox import (
    SQLiteOutboxRepository as DurableOutboxRepository,
)
from caldav_assistant.internal.storage.sqlite import SQLiteOutboxRepository


def test_sqlite_storage_export_points_to_durable_outbox_implementation():
    assert SQLiteOutboxRepository is DurableOutboxRepository


def test_production_service_bootstrap_uses_durable_wordpress_outbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    app = build_service_application()
    outbox = app.wordpress.outbox
    assert isinstance(outbox, DurableOutboxRepository)

    item = outbox.enqueue(
        {
            "schema": 1,
            "request_id": "pytest",
            "operation": "create_log",
            "args": {"text": "queued", "metadata": {}},
        }
    )
    pending = outbox.pending(limit=1)
    assert pending[0]["id"] == item["id"]
    outbox.mark_failed(item["id"], RuntimeError("offline"))
    assert outbox.pending(limit=1)[0]["attempts"] == 1
