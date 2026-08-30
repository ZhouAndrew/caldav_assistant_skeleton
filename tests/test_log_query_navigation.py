from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Activity, Task
from caldav_assistant.internal.cli.navigation import (
    NavigationActions,
    register_navigation_cli_commands,
)
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.runtime.proxies import RemoteWordPressAPI
from caldav_assistant.internal.wordpress.service import WordPressService


class FakeUI:
    def __init__(self, task: Task):
        self.task = task
        self.choices: list[str] = []

    def choose(self, title, items, **options):
        assert self.choices, f"No scripted choice for {title}"
        selected = self.choices.pop(0)
        assert selected in tuple(items)
        return selected

    def choose_task(self, **options):
        return self.task


class FakeTasks:
    def __init__(self, task: Task):
        self.task = task

    def find(self, query, **filters):
        assert query == self.task.summary
        return self.task


class FakeActivity:
    def __init__(self, task: Task):
        stamp = datetime(2026, 8, 30, 0, 30, tzinfo=timezone.utc)
        self.today_items = [
            Activity(stamp, "task_started", task.id, {"priority": 4}),
            Activity(stamp, "task_paused", task.id, {}),
        ]

    def today(self):
        return list(self.today_items)

    def for_task(self, task):
        return [item for item in self.today_items if item.object_id == task.id]


class FakeWordPressQuery:
    def _daily_log(self):
        return {
            "id": 77,
            "title": "August 30 Sunday 2026",
            "content": "<!-- wp:paragraph -->\n<p>08:30 Real entry</p>\n<!-- /wp:paragraph -->",
        }

    def pending(self):
        return [
            {
                "id": 9,
                "created_at": "2026-08-30 08:31:00",
                "attempts": 1,
                "last_error": "wordpress offline",
                "payload": {
                    "request_id": "req-9",
                    "operation": "create_log",
                    "args": {"text": "Pending note"},
                },
            }
        ]


class FakeOutbox:
    def __init__(self):
        self.items = []
        self.next_id = 1

    def enqueue(self, payload):
        item = {
            "id": self.next_id,
            "payload": payload,
            "created_at": "now",
            "attempts": 0,
            "last_error": None,
        }
        self.next_id += 1
        self.items.append(item)
        return dict(item)

    def pending(self, limit=None):
        values = [dict(item) for item in self.items]
        return values if limit is None else values[:limit]

    def mark_sent(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]

    def mark_failed(self, item_id, error):
        for item in self.items:
            if item["id"] == item_id:
                item["attempts"] += 1
                item["last_error"] = str(error)


class FakeWordPressAdapter:
    def __init__(self):
        self.log_calls = []
        self.daily_calls = 0

    def create_log(self, text, **metadata):
        self.log_calls.append((text, metadata))
        return {"id": 101}

    def read_daily_log(self):
        self.daily_calls += 1
        return {"id": 101, "title": "August 30 Sunday 2026", "content": "real"}

    def test_connection(self):
        return True


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {"id": 5}


def make_navigation_ctx():
    task = Task(id="t1", summary="Report")
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(
        tasks=FakeTasks(task),
        activity=FakeActivity(task),
        wordpress=FakeWordPressQuery(),
        ui=FakeUI(task),
        commands=commands,
    )
    return ctx


def test_history_queries_local_sqlite_task_remote_wordpress_and_pending_outbox_views():
    ctx = make_navigation_ctx()
    actions = NavigationActions(ctx)

    local = actions.history("today")
    task = actions.history("task", "Report")
    remote = actions.history("wordpress")
    pending = actions.history("pending")

    assert "Activity Journal · today · local SQLite" in local
    assert "task_started" in local and "task_paused" in local
    assert 'metadata={"priority": 4}' in local
    assert "Activity Journal · Task · Report" in task
    assert "WordPress daily log · today · REAL post_content" in remote
    assert "Post ID: 77" in remote
    assert "08:30 Real entry" in remote
    assert "WordPress Outbox · pending" in pending
    assert "operation=create_log" in pending
    assert "Pending note" in pending
    assert "wordpress offline" in pending


def test_history_without_arguments_opens_log_submenu():
    ctx = make_navigation_ctx()
    ctx.ui.choices = ["WordPress today (real post)"]

    result = NavigationActions(ctx).history()

    assert "REAL post_content" in result


def test_menu_is_multi_level_but_dispatches_to_same_direct_command_registry():
    ctx = make_navigation_ctx()
    calls = []

    ctx.commands.register_builtin("today", lambda: calls.append(("today",)) or "TODAY")
    ctx.commands.register_builtin("start", lambda: calls.append(("start",)) or "START")
    ctx.commands.register_builtin("log", lambda: calls.append(("log",)) or "LOG")
    register_navigation_cli_commands(ctx.commands, ctx)

    # Direct commands still exist beside the optional menu.
    assert {"today", "start", "log", "history", "menu"} <= set(ctx.commands.names())
    assert ctx.commands.resolve("logs").name == "history"
    assert ctx.commands.resolve("m").name == "menu"

    ctx.ui.choices = ["Logs", "WordPress today (real post)"]
    via_menu = ctx.commands.run("menu")
    direct = ctx.commands.run("history", "wordpress")

    assert via_menu == direct
    assert "REAL post_content" in via_menu
    # The menu did not replace or wrap unrelated direct commands.
    assert ctx.commands.run("today") == "TODAY"
    assert calls == [("today",)]


def test_wordpress_log_api_defaults_to_publish_and_private_reader_returns_real_post():
    adapter = FakeWordPressAdapter()
    outbox = FakeOutbox()
    service = WordPressService(adapter, outbox)

    result = service.log("Real daily note")

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert outbox.pending() == []
    assert adapter.log_calls[0][0] == "Real daily note"
    assert adapter.log_calls[0][1]["post_status"] == "publish"
    assert adapter.log_calls[0][1]["_logged_at"]
    assert adapter.log_calls[0][1]["_request_id"]
    assert service._daily_log()["content"] == "real"
    assert adapter.daily_calls == 1


def test_queue_log_keeps_publish_intent_in_durable_outbox():
    adapter = FakeWordPressAdapter()
    outbox = FakeOutbox()
    service = WordPressService(adapter, outbox)

    result = service.queue_log("Paused — Report", title="Paused — Report")

    assert result.success is True
    payload = outbox.pending()[0]["payload"]
    metadata = payload["args"]["metadata"]
    assert metadata["post_status"] == "publish"
    assert metadata["title"] == "Paused — Report"
    assert adapter.log_calls == []


def test_remote_wordpress_daily_log_query_uses_private_runtime_route():
    runtime = FakeRuntime()
    api = RemoteWordPressAPI(runtime)

    assert api._daily_log() == {"id": 5}
    assert runtime.calls == [("wordpress.daily_log", {})]
