from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli import latency_guard, stale_startup_notice


@dataclass(frozen=True)
class _Snapshot:
    current_task: object | None = None
    recommended: object | None = None
    tasks: tuple[Task, ...] = ()
    upcoming: tuple[object, ...] = ()
    stale: bool = False
    warning: str | None = None


def _module(
    *,
    welcome_snapshot: _Snapshot | None = None,
    runtime_call=None,
):
    shown: list[str] = []
    guided_calls: list[tuple[object | None, dict[str, object]]] = []
    runtime_calls: list[tuple[str, dict[str, object]]] = []
    conversation = SimpleNamespace()
    conversation._show = lambda app, value="": shown.append(str(value))
    conversation._snapshot_text = lambda snapshot: "Upcoming"
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()

    def show_welcome(app):
        conversation._show(app, "CalDAV Assistant")
        conversation._show(app, "Now")
        conversation._show(app, "  No Task is currently being worked on.")
        conversation._show(app, "Upcoming")
        assert welcome_snapshot is not None
        return welcome_snapshot

    def guided_start(app, task=None, **options):
        guided_calls.append((task, dict(options)))
        return "wait" if options.get("known_current") is not None else "console"

    def call(method, **payload):
        runtime_calls.append((method, dict(payload)))
        if runtime_call is None:
            return None
        return runtime_call(method, **payload)

    conversation._show_welcome = show_welcome
    conversation._guided_start = guided_start
    module = SimpleNamespace(conversation=conversation)
    runtime = SimpleNamespace(call=call, calls=runtime_calls)
    return module, SimpleNamespace(runtime=runtime), shown, guided_calls


def test_stale_welcome_never_claims_that_no_task_is_active():
    cached = Task(id="t1", summary="Cached", stale=True)
    snapshot = _Snapshot(tasks=(cached,), recommended=cached, stale=True)
    module, app, shown, _calls = _module(welcome_snapshot=snapshot)

    stale_startup_notice.install(module)
    returned = module.conversation._show_welcome(app)

    assert returned is snapshot
    assert "  No Task is currently being worked on." not in shown
    assert any("Current work could not be verified live" in line for line in shown)
    assert shown.index("Now") < next(
        index for index, line in enumerate(shown) if "Current work could not" in line
    )


def test_stale_guided_start_checks_only_live_current_work_then_continues(monkeypatch):
    cached = Task(id="t1", summary="Anki", stale=True)
    module, app, shown, guided_calls = _module(
        welcome_snapshot=_Snapshot(tasks=(cached,), stale=True)
    )

    def full_snapshot_must_not_be_retried(*args, **kwargs):
        raise AssertionError("guided Start must not retry the full startup snapshot")

    monkeypatch.setattr(latency_guard, "_read_snapshot", full_snapshot_must_not_be_retried)
    stale_startup_notice.install(module)

    result = module.conversation._guided_start(
        app,
        cached,
        known_current=None,
        task_choices=(cached,),
    )

    assert result == "console"
    assert app.runtime.calls == [("session.current_task_id", {})]
    assert len(guided_calls) == 1
    task, options = guided_calls[0]
    assert task is cached
    assert options["known_current"] is None
    assert options["task_choices"] == (cached,)
    assert any("checking live current work before Start" in line for line in shown)
    assert not any("still unverified" in line for line in shown)


def test_stale_guided_start_blocks_if_live_current_work_exists(monkeypatch):
    cached = Task(id="t1", summary="Anki", stale=True)
    module, app, shown, guided_calls = _module(
        welcome_snapshot=_Snapshot(tasks=(cached,), stale=True),
        runtime_call=lambda method, **payload: "t2",
    )

    def full_snapshot_must_not_be_retried(*args, **kwargs):
        raise AssertionError("guided Start must not retry the full startup snapshot")

    monkeypatch.setattr(latency_guard, "_read_snapshot", full_snapshot_must_not_be_retried)
    stale_startup_notice.install(module)

    result = module.conversation._guided_start(
        app,
        cached,
        known_current=None,
        task_choices=(cached,),
    )

    assert result == "wait"
    assert app.runtime.calls == [("session.current_task_id", {})]
    assert guided_calls == []
    assert any("already being worked on" in line for line in shown)


def test_stale_guided_start_precheck_timeout_does_not_become_authorization_gate():
    cached = Task(id="t1", summary="Anki", stale=True)

    def unavailable(method, **payload):
        raise RuntimeError("precheck timed out")

    module, app, shown, guided_calls = _module(
        welcome_snapshot=_Snapshot(tasks=(cached,), stale=True),
        runtime_call=unavailable,
    )
    stale_startup_notice.install(module)

    result = module.conversation._guided_start(
        app,
        cached,
        known_current=None,
        task_choices=(cached,),
    )

    assert result == "console"
    assert len(guided_calls) == 1
    assert guided_calls[0][1]["known_current"] is None
    assert any("Start itself will verify live Task and Work state" in line for line in shown)
