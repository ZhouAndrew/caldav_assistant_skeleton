from __future__ import annotations
from typing import Any


class RuntimeDispatcher:
    """Allow-listed service-side IPC dispatcher.

    Runtime transport remains internal; every route terminates at an already
    composed Object/Core API namespace.
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
            "session.current_task_id": ctx.session.current_task_id,
            "session.current_task": ctx.session.current_task,
            "session.paused_task_ids": ctx.session.paused_task_ids,
            "session.paused_tasks": ctx.session.paused_tasks,
            "settings.get": ctx.settings.get,
            "settings.set": ctx.settings.set,
            "settings.reset": ctx.settings.reset,
            "settings.describe": ctx.settings.describe,
            "settings.list": ctx.settings.list,
        }

    def handle(self, method, payload=None):
        if method not in self._routes:
            raise ValueError(f"IPC method is not allowed: {method}")
        return self._routes[method](**(payload or {}))

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
