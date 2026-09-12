"""Application-facing Agenda orchestration service."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta


_WORK_CATEGORY = "caldav-assistant-work"


class AgendaService:
    def __init__(self, tasks, events, engine, next_engine, state, session=None):
        self.tasks = tasks
        self.events = events
        self.engine = engine
        self.next_engine = next_engine
        self.state = state
        self.session = session

    @staticmethod
    def _ordinary_events(items):
        """Hide internal Work VEVENTs from the normal human agenda."""
        return [
            event
            for event in items
            if _WORK_CATEGORY not in set(getattr(event, "categories", ()) or ())
        ]

    @staticmethod
    def _event_window(now: datetime, days: int) -> tuple[datetime, datetime]:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=days)

    def _read_tasks(self, filters):
        task_filters = dict(filters)
        task_filters.setdefault("completed", False)
        return list(self.tasks.list(**task_filters))

    def _read_events(self, event_window, filters):
        event_reader = None
        if event_window is not None:
            event_reader = getattr(self.events, "list_between", None)
        if callable(event_reader):
            start, end = event_window
            values = event_reader(start, end, **filters)
        else:
            values = self.events.list(**filters)
        return self._ordinary_events(values)

    def _sources(self, *, event_window=None, **filters):
        """Read only Task/Event facts that can affect an Agenda decision.

        Task and Event CalDAV REPORTs are independent network operations.  They are
        intentionally executed concurrently here so ordinary agenda reads pay the
        slower of the two network waits rather than their sum.  Business semantics
        remain unchanged: both results are collected before AgendaEngine runs and
        CalDAV remains authoritative.
        """
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="caldav-agenda") as pool:
            task_future = pool.submit(self._read_tasks, filters)
            event_future = pool.submit(self._read_events, event_window, filters)
            tasks = task_future.result()
            events = event_future.result()
        return tasks, events

    def today(self):
        now = datetime.now().astimezone()
        tasks, events = self._sources(event_window=self._event_window(now, 1))
        return self.engine.build(
            tasks,
            events,
            days=1,
            user_state=self.state,
        )

    def range(self, days=1, **filters):
        now = datetime.now().astimezone()
        tasks, events = self._sources(
            event_window=self._event_window(now, days),
            **filters,
        )
        return self.engine.build(
            tasks,
            events,
            days=days,
            user_state=self.state,
        )

    @staticmethod
    def _state_value(state, key, default=None):
        if state is None:
            return default
        if isinstance(state, dict):
            return state.get(key, default)
        getter = getattr(state, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except TypeError:
                value = getter(key)
                return default if value is None else value
        return getattr(state, key, default)

    def _current_task_uid(self):
        if self.session is not None:
            getter = getattr(self.session, "current_task_id", None)
            if callable(getter):
                return getter()
        return self._state_value(self.state, "current_task_uid", None)

    def _paused_task_uids(self):
        if self.session is not None:
            getter = getattr(self.session, "paused_task_ids", None)
            if callable(getter):
                return tuple(getter())
        return tuple(self._state_value(self.state, "paused_task_uids", ()) or ())

    def _session_snapshot(self, tasks, *, work_facts=None):
        """Resolve current/paused work once from an already-read Task set."""
        if self.session is not None:
            snapshot = getattr(self.session, "startup_snapshot", None)
            if callable(snapshot):
                try:
                    value = snapshot(tasks, work_facts=work_facts)
                except TypeError:
                    value = snapshot(tasks)
                if isinstance(value, dict):
                    return {
                        "current_task_id": value.get("current_task_id"),
                        "current_task": value.get("current_task"),
                        "paused_task_ids": tuple(value.get("paused_task_ids") or ()),
                    }

        current_uid = self._current_task_uid()
        paused_uids = self._paused_task_uids()
        current_task = None
        if current_uid:
            current_task = next(
                (
                    task
                    for task in tasks
                    if str(getattr(task, "id", "") or "") == str(current_uid)
                ),
                None,
            )
        return {
            "current_task_id": current_uid,
            "current_task": current_task,
            "paused_task_ids": tuple(paused_uids),
        }

    def _choose_next(self, tasks, events, kind=None, **options):
        agenda = self.engine.candidates(tasks, events)
        values = dict(options)
        values.setdefault("now", datetime.now().astimezone())
        if "current_task_uid" not in values:
            values["current_task_uid"] = self._current_task_uid()
        if "skipped_uids" not in values:
            values["skipped_uids"] = self._paused_task_uids()
        return self.next_engine.choose(agenda, kind=kind, **values)

    def next(self, kind=None, **options):
        if kind == "task":
            tasks = list(self.tasks.list(completed=False))
            events = []
        else:
            tasks, events = self._sources()

        values = dict(options)
        if "current_task_uid" not in values or "skipped_uids" not in values:
            session_snapshot = self._session_snapshot(tasks)
            values.setdefault("current_task_uid", session_snapshot["current_task_id"])
            values.setdefault("skipped_uids", session_snapshot["paused_task_ids"])
        return self._choose_next(tasks, events, kind=kind, **values)

    def startup_snapshot(self, days=1, kind="task"):
        """Return startup current work + Agenda + recommendation from one live read.

        Startup has three independent I/O lanes in production: Task VTODO facts,
        ordinary Event VEVENT facts, and Assistant Work VEVENT facts.  Older code ran
        them serially, so a 3s + 3s + 3s server path became a 9s CLI startup.  The
        three reads now overlap.  Results are joined before any decision is made; no
        cache is promoted to truth and no mutation semantics change.
        """
        now = datetime.now().astimezone()
        event_window = self._event_window(now, days) if kind == "task" else None
        work_reader = getattr(self.session, "startup_work_facts", None)

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="caldav-startup") as pool:
            task_future = pool.submit(self._read_tasks, {})
            event_future = pool.submit(self._read_events, event_window, {})
            work_future = pool.submit(work_reader) if callable(work_reader) else None

            tasks = task_future.result()
            events = event_future.result()
            work_facts = work_future.result() if work_future is not None else None

        session_snapshot = self._session_snapshot(tasks, work_facts=work_facts)
        current_uid = session_snapshot["current_task_id"]
        paused_uids = session_snapshot["paused_task_ids"]
        current_task = session_snapshot["current_task"]

        agenda = self.engine.build(
            tasks,
            events,
            days=days,
            user_state=self.state,
        )
        recommendation = self._choose_next(
            tasks,
            events,
            kind=kind,
            current_task_uid=current_uid,
            skipped_uids=paused_uids,
        )
        return {
            "agenda": agenda,
            "recommendation": recommendation,
            "current_task": current_task,
        }

    def overdue(self):
        return self.tasks.list(overdue=True)
