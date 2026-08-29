"""Application-facing Agenda orchestration service."""
from __future__ import annotations

from datetime import datetime


class AgendaService:
    def __init__(self, tasks, events, engine, next_engine, state):
        self.tasks = tasks
        self.events = events
        self.engine = engine
        self.next_engine = next_engine
        self.state = state

    def today(self):
        return self.engine.build(
            self.tasks.list(),
            self.events.list(),
            days=1,
            user_state=self.state,
        )

    def range(self, days=1, **filters):
        return self.engine.build(
            self.tasks.list(**filters),
            self.events.list(**filters),
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

    def next(self, kind=None, **options):
        # NextEngine consumes one broad candidate Agenda plus explicit human work
        # context. A paused task is intentionally excluded by default; otherwise
        # `pause` would immediately recommend the same work again.
        agenda = self.engine.candidates(
            self.tasks.list(),
            self.events.list(),
        )
        options = dict(options)
        options.setdefault("now", datetime.now().astimezone())
        options.setdefault(
            "current_task_uid",
            self._state_value(self.state, "current_task_uid", None),
        )
        options.setdefault(
            "skipped_uids",
            tuple(self._state_value(self.state, "paused_task_uids", ()) or ()),
        )
        return self.next_engine.choose(agenda, kind=kind, **options)

    def overdue(self):
        return self.tasks.list(overdue=True)
