"""Application-facing Agenda orchestration service."""
from __future__ import annotations

from datetime import datetime


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

    def _sources(self, **filters):
        """Read Task/Event sources once for a composed agenda operation."""
        return (
            list(self.tasks.list(**filters)),
            self._ordinary_events(self.events.list(**filters)),
        )

    def today(self):
        tasks, events = self._sources()
        return self.engine.build(
            tasks,
            events,
            days=1,
            user_state=self.state,
        )

    def range(self, days=1, **filters):
        tasks, events = self._sources(**filters)
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

    def _choose_next(self, tasks, events, kind=None, **options):
        agenda = self.engine.candidates(tasks, events)
        values = dict(options)
        values.setdefault("now", datetime.now().astimezone())
        # Do not use ``dict.setdefault(key, expensive_call())`` here: Python evaluates
        # the default argument even when the caller already supplied the key.  That
        # bug made startup re-read current/paused CalDAV Work state after it had
        # already been resolved from the same snapshot.
        if "current_task_uid" not in values:
            values["current_task_uid"] = self._current_task_uid()
        if "skipped_uids" not in values:
            values["skipped_uids"] = self._paused_task_uids()
        return self.next_engine.choose(agenda, kind=kind, **values)

    def next(self, kind=None, **options):
        # Production work context comes from CalDAVSessionService: one open Work
        # VEVENT means current work; IN-PROCESS VTODOs without that interval are
        # paused. The state fallback exists only for legacy/unit compositions.
        tasks, events = self._sources()
        return self._choose_next(tasks, events, kind=kind, **options)

    def startup_snapshot(self, days=1, kind="task"):
        """Return startup current work + Agenda + recommendation from one source set.

        Task/Event objects are fetched once.  When the production Session service
        provides ``startup_snapshot``, current/paused work is derived from those Task
        objects and one WorkLog read, then passed directly into NextEngine.  This
        removes the old current -> range -> next -> paused chain of repeated CalDAV
        traversals without introducing a cache or changing the source of truth.
        """
        tasks, events = self._sources()

        session_snapshot = None
        if self.session is not None:
            snapshot = getattr(self.session, "startup_snapshot", None)
            if callable(snapshot):
                session_snapshot = snapshot(tasks)

        if isinstance(session_snapshot, dict):
            current_uid = session_snapshot.get("current_task_id")
            paused_uids = tuple(session_snapshot.get("paused_task_ids") or ())
            current_task = session_snapshot.get("current_task")
        else:
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
