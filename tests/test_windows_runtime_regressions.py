from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from caldav_assistant.api import Activity, Task
from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.cli import latency_guard
from caldav_assistant.internal.session import CalDAVSessionService


def test_activity_fallback_prefers_later_row_when_windows_clock_ticks_match():
    """Pause must win even when start/pause receive the same timestamp."""
    timestamp = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    task = Task(id="t1", summary="Report", status="IN-PROCESS")

    class WorkLog:
        def configured(self):
            return False

    class Tasks:
        def list(self, **filters):
            assert filters == {"status": "IN-PROCESS"}
            return [task]

    class ActivitySource:
        def for_task(self, value):
            assert getattr(value, "id", value) == "t1"
            return [
                Activity(timestamp, "task_started", "t1"),
                Activity(timestamp, "task_paused", "t1"),
            ]

    session = CalDAVSessionService(WorkLog(), Tasks(), ActivitySource())

    assert session.current_task_id() is None
    assert session.paused_task_ids() == ("t1",)


def test_guided_start_does_not_issue_second_live_read_after_startup_timeout():
    """The exact Windows human path must stay in the CLI after startup timeout."""
    shown: list[str] = []
    original_calls: list[str] = []
    conversation = SimpleNamespace()

    def original_guided_start(app, task=None):
        original_calls.append("called")
        raise UnavailableError("Runtime request timed out: session.current_task")

    def original_home_menu(app, snapshot):
        return conversation._guided_start(app)

    conversation._guided_start = original_guided_start
    conversation._home_menu = original_home_menu
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()
    conversation._show = lambda app, text="": shown.append(str(text))
    conversation._window_hours = lambda app: 24
    conversation.StartupSnapshot = lambda **kwargs: SimpleNamespace(**kwargs)

    module = SimpleNamespace(
        conversation=conversation,
        legacy=SimpleNamespace(_split_lifecycle_duration=lambda parsed: (parsed, None)),
        base=SimpleNamespace(
            execute_command=lambda app, parsed: SimpleNamespace(
                exit_code=0,
                should_exit=False,
                result=None,
            ),
            _render_result=lambda *args, **kwargs: None,
        ),
        _execute_user=lambda app, parsed, paginate=True: (0, False),
    )

    latency_guard.install(module)
    unavailable = SimpleNamespace(warning="startup live read unavailable")

    result = conversation._home_menu(SimpleNamespace(), unavailable)

    assert result == "console"
    assert original_calls == []
    assert any("cannot safely start another Task" in line for line in shown)
    assert any("No Task state was changed" in line for line in shown)


def test_direct_guided_start_timeout_is_caught_instead_of_escaping_repl():
    shown: list[str] = []
    conversation = SimpleNamespace()

    def original_guided_start(app, task=None):
        raise UnavailableError("Runtime request timed out: session.current_task")

    conversation._guided_start = original_guided_start
    conversation._home_menu = lambda app, snapshot: "console"
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()
    conversation._show = lambda app, text="": shown.append(str(text))
    conversation._window_hours = lambda app: 24
    conversation.StartupSnapshot = lambda **kwargs: SimpleNamespace(**kwargs)

    module = SimpleNamespace(
        conversation=conversation,
        legacy=SimpleNamespace(_split_lifecycle_duration=lambda parsed: (parsed, None)),
        base=SimpleNamespace(
            execute_command=lambda app, parsed: SimpleNamespace(
                exit_code=0,
                should_exit=False,
                result=None,
            ),
            _render_result=lambda *args, **kwargs: None,
        ),
        _execute_user=lambda app, parsed, paginate=True: (0, False),
    )

    latency_guard.install(module)

    assert conversation._guided_start(SimpleNamespace()) == "console"
    assert any("console remains usable" in line.lower() for line in shown)
    assert any("No Task state was changed" in line for line in shown)
