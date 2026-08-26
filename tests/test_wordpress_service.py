from __future__ import annotations

import pytest

from caldav_assistant.api import ActionResult
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.wordpress.service import WordPressService


class FakeOutbox:
    def __init__(self):
        self.items = []
        self.next_id = 1

    def enqueue(self, payload):
        item = {
            "id": self.next_id,
            "payload": payload,
            "created_at": "now",
            "attempts": 0,
            "last_error": None,
        }
        self.next_id += 1
        self.items.append(item)
        return item.copy()

    def pending(self, limit=None):
        items = [dict(item) for item in self.items]
        return items if limit is None else items[:limit]

    def mark_sent(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]

    def mark_failed(self, item_id, error):
        for item in self.items:
            if item["id"] == item_id:
                item["attempts"] += 1
                item["last_error"] = str(error)


class FakeAdapter:
    def __init__(self, available=True):
        self.available = available
        self.calls = []

    def _check(self):
        if not self.available:
            raise OSError("wordpress offline")

    def create_log(self, text, **metadata):
        self._check()
        self.calls.append(("log", text, metadata))
        return {"id": 101}

    def create_post(self, title, content="", **fields):
        self._check()
        self.calls.append(("create", title, content, fields))
        return {"id": 202}

    def update_post(self, post_id, **changes):
        self._check()
        self.calls.append(("update", post_id, changes))
        return {"id": post_id}

    def test_connection(self):
        return self.available


class FakeActivity:
    def __init__(self):
        self.calls = []

    def record(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def make_service(available=True):
    adapter = FakeAdapter(available)
    outbox = FakeOutbox()
    activity = FakeActivity()
    return WordPressService(adapter, outbox, activity), adapter, outbox, activity


def test_log_is_enqueued_before_transport_and_removed_only_after_success():
    service, adapter, outbox, activity = make_service(True)

    result = service.log(" Finished report ", category="work")

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert outbox.pending() == []
    assert adapter.calls == [("log", "Finished report", {"category": "work"})]
    assert activity.calls[-1][0][0] == "wordpress_log_created"


def test_offline_wordpress_keeps_durable_pending_item_and_does_not_raise():
    service, adapter, outbox, activity = make_service(False)

    result = service.log("Saved even while offline")

    assert result.success is True
    assert "pending" in result.message.lower()
    assert len(outbox.pending()) == 1
    assert outbox.pending()[0]["attempts"] == 1
    assert "offline" in outbox.pending()[0]["last_error"]
    assert activity.calls == []

    adapter.available = True
    summary = service.flush()
    assert summary == {"attempted": 1, "sent": 1, "failed": 0, "pending": 0}
    assert outbox.pending() == []
    assert activity.calls[-1][0][0] == "wordpress_log_created"


def test_create_and_update_post_share_the_same_outbox_first_path():
    service, adapter, outbox, _ = make_service(True)

    created = service.create_post("Title", "Body", status="draft")
    updated = service.update_post(202, status="publish")

    assert created.success and updated.success
    assert outbox.pending() == []
    assert adapter.calls == [
        ("create", "Title", "Body", {"status": "draft"}),
        ("update", 202, {"status": "publish"}),
    ]


def test_validation_happens_before_outbox_write():
    service, _, outbox, _ = make_service(True)

    with pytest.raises(ValidationError):
        service.log("  ")
    with pytest.raises(ValidationError):
        service.create_post(" ")
    with pytest.raises(ValidationError):
        service.update_post(1)

    assert outbox.pending() == []
