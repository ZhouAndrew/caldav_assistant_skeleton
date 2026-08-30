from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Activity, Task
from caldav_assistant.internal.cli.actions import BuiltinActions, register_cli_builtin_commands
from caldav_assistant.internal.commands import CommandRegistry, CommandService


class FakeUI:
    def __init__(self):
        self.shown = []

    def show(self, value):
        self.shown.append(str(value))

    def choose_task(self, **kwargs):
        return None


class FakeSettings:
    def __init__(self, worklog="https://dav.example/work/"):
        self.worklog = worklog

    def get(self, key, default=None):
        if key == "caldav.worklog_collection_url":
            return self.worklog
        return default


class FakeActivity:
    def __init__(self):
        self.items = {}

    def add(self, task, action):
        self.items.setdefault(task.id, []).append(
            Activity(
                timestamp=datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc),
                action=action,
                object_id=task.id,
            )
        )

    def for_task(self, task):
        return list(self.items.get(task.id, ()))


class FakeSession:
    def __init__(self, task):
        self.current = task
        self.paused = []

    def current_task(self):
        return self.current

    def paused_tasks(self):
        return list(self.paused)


class FakeTasks:
    def __init__(self, task, session, activity):
        self.task = task
        self.session = session
        self.activity = activity

    def list(self, **filters):
        return [self.task]

    def find(self, query, **filters):
        return self.task

    def pause(self, task):
        self.session.current = None
        self.session.paused = [task]
        self.activity.add(task, "task_paused")
        return ActionResult(True, affected=task)

    def resume(self, task):
        self.session.current = task
        self.session.paused = []
        self.activity.add(task, "task_resumed")
        return ActionResult(True, affected=task)

    def start(self, task):
        task.status = "IN-PROCESS"
        self.session.current = task
        self.activity.add(task, "task_started")
        return ActionResult(True, affected=task)

    def complete(self, task):
        task.status = "COMPLETED"
        task.completed = True
        task.completed_at = datetime(2026, 8, 30, 6, 5, tzinfo=timezone.utc)
        self.session.current = None
        self.activity.add(task, "task_completed")
        return ActionResult(True, affected=task, undo_available=True)


class FakeWordPress:
    def log(self, text):
        return ActionResult(True, message="uploaded")


def make_ctx():
    task = Task(id="t1", summary="Report", status="IN-PROCESS")
    activity = FakeActivity()
    session = FakeSession(task)
    tasks = FakeTasks(task, session, activity)
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(
        ui=FakeUI(),
        settings=FakeSettings(),
        activity=activity,
        session=session,
        tasks=tasks,
        commands=commands,
        wordpress=FakeWordPress(),
        agenda=SimpleNamespace(today=lambda: [], next=lambda **kwargs: None),
        time=SimpleNamespace(),
    )
    register_cli_builtin_commands(commands, ctx)
    return ctx, task


def test_help_pause_explains_meaning_storage_non_effects_and_verification():
    ctx, _ = make_ctx()

    text = ctx.commands.run("help", "pause")

    assert "Usage: pause" in text
    assert "Meaning:" in text
    assert "Writes / changes:" in text
    assert "CalDAV Work VEVENT" in text
    assert "Activity Journal (SQLite)" in text
    assert "VTODO remains STATUS:IN-PROCESS" in text
    assert "WordPress/Outbox" in text
    assert "history pending" in text
    assert "source:" in text


def test_pause_result_tells_user_exactly_which_layers_changed():
    ctx, task = make_ctx()

    result = BuiltinActions(ctx).pause()

    assert result.success is True
    assert "Paused work: Report" in result.message
    assert "CalDAV VTODO: remains STATUS:IN-PROCESS" in result.message
    assert "CalDAV Work VEVENT: closed the current interval" in result.message
    assert "https://dav.example/work/" in result.message
    assert "Activity Journal (SQLite): task_paused recorded" in result.message
    assert "Hook: task.paused emitted" in result.message
    assert "history pending / history wordpress" in result.message
    assert task in ctx.session.paused


def test_resume_and_done_results_distinguish_work_interval_from_task_completion():
    ctx, task = make_ctx()
    BuiltinActions(ctx).pause()

    resumed = BuiltinActions(ctx).resume()
    assert "CalDAV Work VEVENT: opened a new work interval" in resumed.message
    assert "planned DTSTART is unchanged" in resumed.message

    done = BuiltinActions(ctx).done()
    assert "Completed task: Report" in done.message
    assert "CalDAV VTODO: STATUS -> COMPLETED" in done.message
    assert "CalDAV Work VEVENT: closed the current work interval" in done.message
    assert "Activity Journal (SQLite): task_completed recorded" in done.message
    assert "Undo: available" in done.message


def test_log_result_explains_outbox_and_real_wordpress_verification():
    ctx, _ = make_ctx()

    result = BuiltinActions(ctx).log("Finished", "chapter", "3")

    assert result.success is True
    assert "Long-term log accepted" in result.message
    assert "durable Outbox" in result.message
    assert "Task/Event state: unchanged" in result.message
    assert "Delivery status: uploaded" in result.message
    assert "history pending" in result.message
    assert "history wordpress" in result.message


def test_help_list_tells_user_how_to_get_effect_and_storage_details():
    ctx, _ = make_ctx()

    text = ctx.commands.run("help")

    assert "help <command>" in text
    assert "data writes" in text
    assert "history" in text
