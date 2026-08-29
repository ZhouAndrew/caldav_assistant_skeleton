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

    def today(self):
        return self.engine.build(
            self.tasks.list(),
            self._ordinary_events(self.events.list()),
            days=1,
            user_state=self.state,
        )

    def range(self, days=1, **filters):
        return self.engine.build(
            self.tasks.list(**filters),
            self._ordinary_events(self.events.list(**filters)),
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

    def next(self, kind=None, **options):
        # Production work context comes from CalDAVSessionService: one open Work
        # VEVENT means current work; IN-PROCESS VTODOs without that interval are
        # paused. The state fallback exists only for legacy/unit compositions.
        agenda = self.engine.candidates(
            self.tasks.list(),
            self._ordinary_events(self.events.list()),
        )
        options = dict(options)
        options.setdefault("now", datetime.now().astimezone())
        options.setdefault("current_task_uid", self._current_task_uid())
        options.setdefault("skipped_uids", self._paused_task_uids())
        return self.next_engine.choose(agenda, kind=kind, **options)

    def overdue(self):
        return self.tasks.list(overdue=True)
