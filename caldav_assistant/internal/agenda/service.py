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
        values.setdefault("current_task_uid", self._current_task_uid())
        values.setdefault("skipped_uids", self._paused_task_uids())
        return self.next_engine.choose(agenda, kind=kind, **values)

    def next(self, kind=None, **options):
        # Production work context comes from CalDAVSessionService: one open Work
        # VEVENT means current work; IN-PROCESS VTODOs without that interval are
        # paused. The state fallback exists only for legacy/unit compositions.
        tasks, events = self._sources()
        return self._choose_next(tasks, events, kind=kind, **options)

    def startup_snapshot(self, days=1, kind="task"):
        """Return startup Agenda + recommendation from one Task/Event read.

        The zero-learning CLI needs both Upcoming and Recommended. Calling ``range``
        and then ``next`` used to perform two complete CalDAV Task/Event traversals,
        which made startup roughly twice as slow on real collections. This internal
        composition reuses the same source objects without changing Agenda/Next rules.
        """
        tasks, events = self._sources()
        agenda = self.engine.build(
            tasks,
            events,
            days=days,
            user_state=self.state,
        )
        recommendation = self._choose_next(tasks, events, kind=kind)
        return {"agenda": agenda, "recommendation": recommendation}

    def overdue(self):
        return self.tasks.list(overdue=True)
