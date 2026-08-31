from __future__ import annotations
from typing import Any

from ..progress import operation_scope


_OPERATION_ID_KEY = "__operation_id"


class RuntimeDispatcher:
    """Allow-listed service-side IPC dispatcher.

    Runtime transport remains internal; every route terminates at an already
    composed Object/Core API namespace. A reserved internal operation id may be
    attached by the foreground client so factual Core milestones can be streamed
    back while the request is still executing.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self._routes = {
            "tasks.list": ctx.tasks.list,
            "tasks.find": ctx.tasks.find,
            "tasks.get": ctx.tasks.get,
            "tasks.create": ctx.tasks.create,
            "tasks.update": ctx.tasks.update,
            "tasks.complete": ctx.tasks.complete,
            "tasks.start": ctx.tasks.start,
            "tasks.pause": ctx.tasks.pause,
            "tasks.resume": ctx.tasks.resume,
            "tasks.delete": ctx.tasks.delete,
            "events.list": ctx.events.list,
            "events.find": ctx.events.find,
            "events.get": ctx.events.get,
            "events.create": ctx.events.create,
            "events.update": ctx.events.update,
            "events.delete": ctx.events.delete,
            "agenda.today": ctx.agenda.today,
            "agenda.range": ctx.agenda.range,
            "agenda.next": ctx.agenda.next,
            "agenda.overdue": ctx.agenda.overdue,
            "reminders.list": ctx.reminders.list,
            "reminders.create": ctx.reminders.create,
            "reminders.snooze": ctx.reminders.snooze,
            "reminders.cancel": ctx.reminders.cancel,
            "notifications.send": ctx.notifications.send,
            "wordpress.log": ctx.wordpress.log,
            "wordpress.create_post": ctx.wordpress.create_post,
            "wordpress.update_post": ctx.wordpress.update_post,
            "wordpress.pending": ctx.wordpress.pending,
            "activity.today": ctx.activity.today,
            "activity.for_task": ctx.activity.for_task,
            "activity.record": ctx.activity.record,
            "settings.get": ctx.settings.get,
            "settings.set": ctx.settings.set,
            "settings.reset": ctx.settings.reset,
            "settings.describe": ctx.settings.describe,
            "settings.list": ctx.settings.list,
        }

        # Startup needs Upcoming + Recommended from the same source read. Keep this
        # as an internal runtime route rather than widening the frozen Public API.
        startup_snapshot = getattr(ctx.agenda, "startup_snapshot", None)
        if callable(startup_snapshot):
            self._routes["agenda.startup_snapshot"] = startup_snapshot

        # CLI-only observability intentionally stays outside the frozen public
        # WordPressAPI. Small test contexts can omit it without becoming invalid.
        daily_log = getattr(ctx.wordpress, "_daily_log", None)
        if callable(daily_log):
            self._routes["wordpress.daily_log"] = daily_log

        # Session is part of the full v1 AssistantContext, but keeping these routes
        # conditional lets small unit/integration test contexts remain deliberately
        # partial instead of forcing unrelated fake namespaces everywhere.
        session = getattr(ctx, "session", None)
        if session is not None:
            self._routes.update(
                {
                    "session.current_task_id": session.current_task_id,
                    "session.current_task": session.current_task,
                    "session.paused_task_ids": session.paused_task_ids,
                    "session.paused_tasks": session.paused_tasks,
                }
            )

    def handle(self, method, payload=None):
        if method not in self._routes:
            raise ValueError(f"IPC method is not allowed: {method}")
        values = dict(payload or {})
        operation_id = values.pop(_OPERATION_ID_KEY, None)
        with operation_scope(operation_id):
            return self._routes[method](**values)

    def register_internal(self, method: str, handler: Any) -> None:
        """Register one explicit service-side integration route."""
        if not isinstance(method, str) or not method.strip():
            raise ValueError("Runtime route must be non-empty text")
        clean = method.strip()
        if not callable(handler):
            raise TypeError("Runtime route handler must be callable")
        if clean in self._routes:
            raise ValueError(f"Runtime route already registered: {clean}")
        self._routes[clean] = handler
