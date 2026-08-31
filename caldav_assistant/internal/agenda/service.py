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
        """Read only the Task/Event facts that can affect an Agenda decision.

        Completed Tasks are never eligible for Agenda or Next.  Passing the
        explicit ``completed=False`` filter lets the CalDAV adapter translate this
        invariant into a server-side pending-VTODO query instead of downloading a
        potentially large completed-task history and discarding it afterwards.
        Event filters remain unchanged because Event objects have no ``completed``
        field.
        """
        task_filters = dict(filters)
        task_filters.setdefault("completed", False)
        return (
            list(self.tasks.list(**task_filters)),
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

    def _session_snapshot(self, tasks):
        """Resolve current/paused work once from an already-read Task set."""
        if self.session is not None:
            snapshot = getattr(self.session, "startup_snapshot", None)
            if callable(snapshot):
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
        # Reuse the Tasks already fetched for this command when resolving current
        # and paused work.  The older path called current_task_id(), paused_task_ids()
        # and tasks.list() independently, multiplying one user command into several
        # CalDAV traversals.
        tasks, events = self._sources()
        values = dict(options)
        if "current_task_uid" not in values or "skipped_uids" not in values:
            session_snapshot = self._session_snapshot(tasks)
            values.setdefault("current_task_uid", session_snapshot["current_task_id"])
            values.setdefault("skipped_uids", session_snapshot["paused_task_ids"])
        return self._choose_next(tasks, events, kind=kind, **values)

    def startup_snapshot(self, days=1, kind="task"):
        """Return startup current work + Agenda + recommendation from one source set.

        Task/Event objects are fetched once.  When the production Session service
        provides ``startup_snapshot``, current/paused work is derived from those Task
        objects and one WorkLog read, then passed directly into NextEngine.  This
        removes the old current -> range -> next -> paused chain of repeated CalDAV
        traversals without introducing a cache or changing the source of truth.
        """
        tasks, events = self._sources()
        session_snapshot = self._session_snapshot(tasks)
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
