"""Synchronous Object-API proxies over RuntimeClient."""
from __future__ import annotations
from typing import Any

class _RemoteAPI:
    prefix = ""
    def __init__(self, runtime: Any) -> None: self.runtime = runtime
    def _call(self, name: str, **payload: Any): return self.runtime.call(f"{self.prefix}.{name}", **payload)

class RemoteTasksAPI(_RemoteAPI):
    prefix="tasks"
    def __init__(self, runtime): super().__init__(runtime); runtime.bind_domain("task", self)
    def list(self, **filters): return self._call("list", **filters)
    def find(self, query, **filters): return self._call("find", query=query, **filters)
    def get(self, task): return self._call("get", task=task)
    def create(self, summary, **fields): return self._call("create", summary=summary, **fields)
    def update(self, task, **changes): return self._call("update", task=task, **changes)
    def complete(self, task): return self._call("complete", task=task)
    def start(self, task): return self._call("start", task=task)
    def pause(self, task): return self._call("pause", task=task)
    def resume(self, task): return self._call("resume", task=task)
    def delete(self, task): return self._call("delete", task=task)

class RemoteEventsAPI(_RemoteAPI):
    prefix="events"
    def __init__(self, runtime): super().__init__(runtime); runtime.bind_domain("event", self)
    def list(self, **filters): return self._call("list", **filters)
    def find(self, query, **filters): return self._call("find", query=query, **filters)
    def get(self, event): return self._call("get", event=event)
    def create(self, summary, **fields): return self._call("create", summary=summary, **fields)
    def update(self, event, **changes): return self._call("update", event=event, **changes)
    def delete(self, event): return self._call("delete", event=event)

class RemoteAgendaAPI(_RemoteAPI):
    prefix="agenda"
    def today(self): return self._call("today")
    def range(self, **options): return self._call("range", **options)
    def next(self, kind=None, **options): return self._call("next", kind=kind, **options)
    def overdue(self): return self._call("overdue")

class RemoteRemindersAPI(_RemoteAPI):
    prefix="reminders"
    def list(self, **filters): return self._call("list", **filters)
    def create(self, title, when, **options): return self._call("create", title=title, when=when, **options)
    def snooze(self, reminder, until): return self._call("snooze", reminder=reminder, until=until)
    def cancel(self, reminder): return self._call("cancel", reminder=reminder)

class RemoteNotificationsAPI(_RemoteAPI):
    prefix="notifications"
    def send(self, title, body="", actions=None): return self._call("send", title=title, body=body, actions=actions)

class RemoteWordPressAPI(_RemoteAPI):
    prefix="wordpress"
    def log(self, text, **metadata): return self._call("log", text=text, **metadata)
    def create_post(self, title, content="", **metadata): return self._call("create_post", title=title, content=content, **metadata)
    def update_post(self, post_id, **changes): return self._call("update_post", post_id=post_id, **changes)
    def pending(self): return self._call("pending")

class RemoteActivityAPI(_RemoteAPI):
    prefix="activity"
    def today(self): return self._call("today")
    def for_task(self, task): return self._call("for_task", task=task)
    def record(self, action, object_id=None, **metadata): return self._call("record", action=action, object_id=object_id, **metadata)

class RemoteSessionAPI(_RemoteAPI):
    prefix="session"
    def __init__(self, runtime):
        super().__init__(runtime)
        self.last_items = []
        self.current_selection = None
    def current_task_id(self): return self._call("current_task_id")
    def current_task(self): return self._call("current_task")
    def paused_task_ids(self): return tuple(self._call("paused_task_ids") or ())
    def paused_tasks(self): return list(self._call("paused_tasks") or ())
    def work_segments(self, task): return list(self._call("work_segments", task=task) or ())
    def work_seconds(self, task): return float(self._call("work_seconds", task=task) or 0.0)

class RemoteSettingsAPI(_RemoteAPI):
    prefix="settings"
    def get(self, key, default=None): return self._call("get", key=key, default=default)
    def set(self, key, value): return self._call("set", key=key, value=value)
    def reset(self, key): return self._call("reset", key=key)
    def describe(self, key): return self._call("describe", key=key)
    def list(self, category=None): return self._call("list", category=category)

    def _caldav_call(self, name: str, **payload: Any):
        return self.runtime.call(f"caldav.{name}", **payload)

    def caldav_status(self): return self._caldav_call("status")
    def set_caldav_base_url(self, value: str): return self._caldav_call("set_base_url", value=value)
    def set_caldav_credentials(self, username: str, password: str):
        return self._caldav_call("set_credentials", username=username, password=password)
    def clear_caldav_credentials(self): return self._caldav_call("clear_credentials")
    def test_caldav_connection(self): return self._caldav_call("test")
    def caldav_collections(self): return self._caldav_call("collections")

__all__ = [
    "RemoteTasksAPI","RemoteEventsAPI","RemoteAgendaAPI","RemoteRemindersAPI",
    "RemoteNotificationsAPI","RemoteWordPressAPI","RemoteActivityAPI",
    "RemoteSessionAPI","RemoteSettingsAPI"
]
