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
        # ``today`` is an Agenda projection, not a CalDAV object attribute/filter.
        # Read authoritative objects normally and let AgendaEngine apply its
        # timezone-aware one-day range plus current/overdue visibility rules.
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
        # NextEngine consumes one Agenda plus explicit decision context.  The
        # candidate projection is deliberately broad so undated Tasks remain
        # eligible; date/event horizons are NextEngine policy, not CalDAV filters.
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
        return self.next_engine.choose(agenda, kind=kind, **options)

    def overdue(self):
        return self.tasks.list(overdue=True)
