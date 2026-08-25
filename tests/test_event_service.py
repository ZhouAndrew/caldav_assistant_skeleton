from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import ActionResult, Event
from caldav_assistant.api.v1.errors import (
    AmbiguousError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from caldav_assistant.internal.events import EventService


class FakeAdapter:
    def __init__(self):
        self.items = {
            "1": Event(
                id="1",
                summary="English lesson",
                start=datetime(2026, 8, 25, 17, 0, tzinfo=timezone.utc),
                end=datetime(2026, 8, 25, 17, 30, tzinfo=timezone.utc),
            ),
            "2": Event(id="2", summary="English planning"),
        }
        self.calls = []
        self.fail_update = False

    def list_events(self, **filters):
        self.calls.append(("list", filters))
        return list(self.items.values())

    def get_event(self, event_id):
        if event_id not in self.items:
            raise KeyError(event_id)
        return self.items[event_id]

    def create_event(self, event):
        self.calls.append(("create", event))
        created = Event(
            **{
                key: value
                for key, value in event.__dict__.items()
                if key != "_service"
            }
        )
        created.id = "3"
        self.items[created.id] = created
        return created

    def update_event(self, event_id, changes, *, etag=None):
        self.calls.append(("update", event_id, changes))
        if self.fail_update:
            raise ConflictError(event_id)

        old = self.items[event_id]
        values = {
            key: value
            for key, value in old.__dict__.items()
            if key != "_service"
        }
        values.update(changes)
        updated = Event(**values)
        self.items[event_id] = updated
        return updated

    def delete_event(self, event_id, *, etag=None):
        self.calls.append(("delete", event_id))
        del self.items[event_id]


class FakeActivity:
    def __init__(self):
        self.calls = []

    def record(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class FakeUndo:
    def __init__(self):
        self.calls = []

    def remember(self, payload):
        self.calls.append(payload)


def make_service():
    adapter = FakeAdapter()
    activity = FakeActivity()
    undo = FakeUndo()
    return (
        EventService(adapter, activity, undo),
        adapter,
        activity,
        undo,
    )


def test_list_forwards_filters_binds_service_and_find_prefers_exact_match():
    service, adapter, _, _ = make_service()

    items = service.list(today=True)

    assert adapter.calls[-1] == ("list", {"today": True})
    assert items[0]._service is service
    assert service.find("english lesson").id == "1"


def test_find_uses_stable_public_errors():
    service, _, _, _ = make_service()

    with pytest.raises(NotFoundError):
        service.find("missing")

    with pytest.raises(AmbiguousError):
        service.find("english")

    with pytest.raises(ValidationError):
        service.find(" ")


def test_get_maps_simple_adapter_keyerror_to_not_found():
    service, _, _, _ = make_service()

    with pytest.raises(NotFoundError):
        service.get("missing")


def test_create_returns_action_result_and_records_side_effects():
    service, _, activity, undo = make_service()

    result = service.create(
        " New event ",
        start=date(2026, 8, 30),
        categories=("school",),
    )

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.affected.summary == "New event"
    assert result.affected.start == date(2026, 8, 30)
    assert result.affected.categories == ["school"]
    assert result.affected._service is service
    assert result.undo_available is True
    assert activity.calls[-1][0][0] == "event_created"
    assert undo.calls[-1]["action"] == "event.create"


def test_create_rejects_unknown_fields_and_empty_summary():
    service, _, _, _ = make_service()

    with pytest.raises(ValidationError):
        service.create(" ")

    with pytest.raises(ValidationError):
        service.create("Meeting", priority=1)


def test_update_does_not_mutate_before_authoritative_write_succeeds():
    service, adapter, activity, undo = make_service()
    event = service.get("1")
    adapter.fail_update = True

    with pytest.raises(ConflictError):
        service.update(event, location="Room 2")

    assert event.location == ""
    assert activity.calls == []
    assert undo.calls == []


def test_update_validates_fields_and_records_undo_after_success():
    service, adapter, activity, undo = make_service()

    result = service.update(
        "1",
        location="Room 2",
        categories=("english", "lesson"),
    )

    assert adapter.calls[-1][0] == "update"
    assert result.affected.location == "Room 2"
    assert result.affected.categories == ["english", "lesson"]
    assert result.undo_available is True
    assert undo.calls[-1]["action"] == "event.update"
    assert undo.calls[-1]["before"]["location"] == ""
    assert activity.calls[-1][0][0] == "event_updated"

    with pytest.raises(ValidationError):
        service.update("1", end="tomorrow")


def test_delete_records_reconstructable_snapshot_for_undo():
    service, adapter, activity, undo = make_service()

    result = service.delete("1")

    assert "1" not in adapter.items
    assert result.undo_available is True
    assert undo.calls[-1]["action"] == "event.delete"
    assert undo.calls[-1]["event"]["summary"] == "English lesson"
    assert "raw" not in undo.calls[-1]["event"]
    assert activity.calls[-1][0][0] == "event_deleted"
