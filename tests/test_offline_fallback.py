from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api import Agenda, Event, Task
from caldav_assistant.api.v1.errors import UnavailableError, ValidationError
from caldav_assistant.internal.caldav import OfflineFallbackCalDAVAdapter
from caldav_assistant.internal.cli import presenter, stale_startup_notice


class _Sync:
    SCHEMA_VERSION = 1

    def __init__(self, snapshot=True):
        self.snapshot = (
            {
                "schema_version": 1,
                "synced_at": "2026-09-12T00:00:00Z",
                "tasks": [],
                "events": [],
            }
            if snapshot
            else None
        )
        self.tasks = [
            Task(id="open", summary="Cached open"),
            Task(id="done", summary="Cached done", completed=True, status="COMPLETED"),
        ]
        self.events = [Event(id="event", summary="Cached event")]

    def cached_snapshot(self):
        return self.snapshot

    def cached_tasks(self):
        return list(self.tasks)

    def cached_events(self):
        return list(self.events)


def test_healthy_read_remains_live_and_is_not_marked_stale():
    live = Task(id="live", summary="Server truth")
    adapter = SimpleNamespace(list_tasks=lambda **filters: [live])
    fallback = OfflineFallbackCalDAVAdapter(adapter, _Sync())

    assert fallback.list_tasks() == [live]
    assert fallback.list_tasks()[0].stale is False
    assert fallback.fallback_generation == 0


def test_unavailable_read_uses_only_matching_verified_cache_and_marks_it_stale():
    def unavailable(**filters):
        raise UnavailableError("server unavailable")

    fallback = OfflineFallbackCalDAVAdapter(
        SimpleNamespace(list_tasks=unavailable),
        _Sync(),
    )

    values = fallback.list_tasks(completed=False)

    assert [task.id for task in values] == ["open"]
    assert values[0].stale is True
    assert values[0]._service is None
    assert fallback.fallback_generation == 1


def test_no_verified_snapshot_preserves_unknown_instead_of_faking_empty():
    def unavailable(**filters):
        raise UnavailableError("server unavailable")

    fallback = OfflineFallbackCalDAVAdapter(
        SimpleNamespace(list_events=unavailable),
        _Sync(snapshot=False),
    )

    with pytest.raises(UnavailableError, match="No verified"):
        fallback.list_events()


def test_malformed_snapshot_preserves_unknown_instead_of_faking_empty():
    def unavailable(**filters):
        raise UnavailableError("server unavailable")

    sync = _Sync()
    sync.snapshot = {"schema_version": 1, "synced_at": "2026-09-12T00:00:00Z"}
    fallback = OfflineFallbackCalDAVAdapter(
        SimpleNamespace(list_tasks=unavailable),
        sync,
    )

    with pytest.raises(UnavailableError, match="No verified"):
        fallback.list_tasks()


def test_only_availability_failures_fall_back_and_mutations_always_go_live():
    calls = []

    def invalid(**filters):
        raise ValidationError("bad query")

    def update(task_id, changes):
        calls.append((task_id, changes))
        raise UnavailableError("write unavailable")

    fallback = OfflineFallbackCalDAVAdapter(
        SimpleNamespace(list_tasks=invalid, update_task=update),
        _Sync(),
    )

    with pytest.raises(ValidationError, match="bad query"):
        fallback.list_tasks()
    with pytest.raises(UnavailableError, match="write unavailable"):
        fallback.update_task("open", {"summary": "Must reach CalDAV"})
    assert calls == [("open", {"summary": "Must reach CalDAV"})]


def test_even_empty_cached_agenda_is_visibly_stale():
    assert presenter.render_agenda(Agenda(stale=True)) == [
        "Cached data — live CalDAV is unavailable; this may be out of date.",
        "Nothing scheduled.",
    ]


def test_home_snapshot_stale_warning_cannot_be_hidden_by_other_renderers():
    conversation = SimpleNamespace(_snapshot_text=lambda snapshot: "home")
    module = SimpleNamespace(conversation=conversation)
    stale_startup_notice.install(module)

    text = conversation._snapshot_text(SimpleNamespace(stale=True, tasks=(), upcoming=()))

    assert "Cached Task/Event data" in text
    assert text.endswith("home")
