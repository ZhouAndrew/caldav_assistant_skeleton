from __future__ import annotations

from datetime import datetime, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.worklog.service import WorkLogService


WORK_URL = "https://dav.example/work"


def _event(uid: str, task_id: str, *, open_: bool, minute: int = 0) -> Event:
    start = datetime(2026, 9, 6, 8, minute, tzinfo=timezone.utc)
    event = Event(
        id=uid,
        summary=f"Work {task_id}",
        start=start,
        end=None if open_ else datetime(2026, 9, 6, 8, minute + 1, tzinfo=timezone.utc),
        description=WorkLogService._description(task_id),
        categories=[
            WorkLogService.CATEGORY,
            *([WorkLogService.OPEN_CATEGORY] if open_ else []),
        ],
    )
    event._caldav_collection_url = WORK_URL
    return event


class CapturingAdapter:
    def __init__(self, events):
        self.events = list(events)
        self.calls = []

    def list_events_in_collection(self, collection_url, **filters):
        self.calls.append((collection_url, dict(filters)))
        values = list(self.events)
        category = filters.get("category")
        if category:
            values = [item for item in values if category in set(item.categories)]
        description = filters.get("description")
        if description:
            values = [item for item in values if item.description == description]
        return values


def test_standalone_current_queries_only_open_category_not_full_work_history():
    adapter = CapturingAdapter(
        [
            *[_event(f"old-{i}", f"t-{i}", open_=False) for i in range(20)],
            _event("open", "current", open_=True),
        ]
    )
    worklog = WorkLogService(adapter, lambda: WORK_URL)

    assert worklog.current_task_id() == "current"
    assert adapter.calls == [
        (WORK_URL, {"category": WorkLogService.OPEN_CATEGORY})
    ]


def test_standalone_segments_query_is_narrowed_by_category_and_exact_description():
    adapter = CapturingAdapter(
        [
            _event("a", "wanted", open_=False, minute=2),
            _event("b", "other", open_=False, minute=1),
            _event("c", "wanted", open_=False, minute=0),
        ]
    )
    worklog = WorkLogService(adapter, lambda: WORK_URL)

    values = worklog.segments_for(Task(id="wanted", summary="Wanted"))

    assert [item.id for item in values] == ["c", "a"]
    assert adapter.calls == [
        (
            WORK_URL,
            {
                "category": WorkLogService.CATEGORY,
                "description": WorkLogService._description("wanted"),
            },
        )
    ]


def test_explicit_command_snapshot_never_triggers_targeted_followup_reads():
    adapter = CapturingAdapter([])
    worklog = WorkLogService(adapter, lambda: WORK_URL)
    snapshot = (
        _event("old", "wanted", open_=False),
        _event("open", "wanted", open_=True, minute=2),
    )

    assert worklog.current_task_id(snapshot=snapshot) == "wanted"
    assert worklog.open_for("wanted", snapshot=snapshot).id == "open"
    assert [item.id for item in worklog.segments_for("wanted", snapshot=snapshot)] == [
        "old",
        "open",
    ]
    assert adapter.calls == []


def test_snapshot_still_requests_full_assistant_work_category_for_paused_semantics():
    adapter = CapturingAdapter([_event("old", "wanted", open_=False)])
    worklog = WorkLogService(adapter, lambda: WORK_URL)

    assert [item.id for item in worklog.snapshot()] == ["old"]
    assert adapter.calls == [
        (WORK_URL, {"category": WorkLogService.CATEGORY})
    ]
