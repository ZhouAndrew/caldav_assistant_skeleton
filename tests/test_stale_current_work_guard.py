from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli import stale_startup_notice


@dataclass(frozen=True)
class _Snapshot:
    current_task: object | None = None
    recommended: object | None = None
    tasks: tuple[Task, ...] = ()
    upcoming: tuple[object, ...] = ()
    stale: bool = False
    warning: str | None = None


def _module(*, welcome_snapshot: _Snapshot | None = None, runtime_call=None):
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


def test_stale_welcome_labels_background_no_current_without_claiming_live_truth():
    cached = Task(id="t1", summary="Cached", stale=True)
    snapshot = _Snapshot(tasks=(cached,), recommended=cached, stale=True)
    module, app, shown, _calls = _module(welcome_snapshot=snapshot)

    stale_startup_notice.install(module)
    returned = module.conversation._show_welcome(app)

    assert returned is snapshot
    assert "  No Task is currently being worked on." not in shown
    assert any("Background snapshot has no current Task" in line for line in shown)
    assert shown.index("Now") < next(
        index for index, line in enumerate(shown)
        if "Background snapshot has no current Task" in line
    )


def test_stale_welcome_guard_survives_installed_live_composition_order():
    cached = Task(id="t1", summary="Cached", stale=True)
    snapshot = _Snapshot(tasks=(cached,), recommended=cached, stale=True)
    module, app, shown, _calls = _module(welcome_snapshot=snapshot)
    conversation = module.conversation

    def live_show_welcome(current_app):
        conversation._show(current_app, "CalDAV Assistant")
        conversation._show(current_app, "Now")
        conversation._show(current_app, "  No Task is currently being worked on.")
        conversation._show(current_app, conversation._snapshot_text(snapshot))
        return snapshot

    module._show_welcome = live_show_welcome
    stale_startup_notice.install(module)
    conversation._show_welcome = module._show_welcome

    returned = conversation._show_welcome(app)

    assert returned is snapshot
    assert "  No Task is currently being worked on." not in shown
    assert any("Background snapshot has no current Task" in line for line in shown)
    assert any("Warning: Cached Task/Event data" in line for line in shown)


def test_stale_guided_start_adds_no_duplicate_runtime_precheck():
    """UI must not repeat the live Work query already owned by Core Task.start()."""
    cached = Task(id="t1", summary="Anki", stale=True)
    module, app, shown, guided_calls = _module(
        welcome_snapshot=_Snapshot(tasks=(cached,), stale=True),
        runtime_call=lambda method, **payload: (_ for _ in ()).throw(
            AssertionError("stale presentation must not query live current work")
        ),
    )

    original = module.conversation._guided_start
    stale_startup_notice.install(module)

    assert module.conversation._guided_start is original
    result = module.conversation._guided_start(
        app,
        cached,
        known_current=None,
        task_choices=(cached,),
    )

    assert result == "console"
    assert app.runtime.calls == []
    assert len(guided_calls) == 1
    task, options = guided_calls[0]
    assert task is cached
    assert options["known_current"] is None
    assert options["task_choices"] == (cached,)
    assert not any("checking live current work before Start" in line for line in shown)


def test_cached_current_task_is_shown_as_background_state():
    current = Task(id="current", summary="Current", status="IN-PROCESS", stale=True)
    snapshot = _Snapshot(current_task=current, tasks=(current,), stale=True)
    shown: list[str] = []
    conversation = SimpleNamespace()
    conversation._show = lambda app, value="": shown.append(str(value))
    conversation._snapshot_text = lambda value: "Upcoming"

    def show_welcome(app):
        conversation._show(app, "Now")
        conversation._show(app, "  ▶ Current")
        return snapshot

    conversation._show_welcome = show_welcome
    module = SimpleNamespace(conversation=conversation)

    stale_startup_notice.install(module)
    returned = conversation._show_welcome(SimpleNamespace())

    assert returned is snapshot
    assert any("▶ Current" in line and "[background snapshot]" in line for line in shown)
