from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.cli import latency_guard


@dataclass(frozen=True)
class _Snapshot:
    warning: str | None = None


class _Conversation(SimpleNamespace):
    pass


def _module(read_snapshot, shown):
    conversation = _Conversation()
    conversation.StartupSnapshot = lambda **kwargs: _Snapshot(kwargs.get("warning"))
    conversation._window_hours = lambda app: 24
    conversation._show = lambda app, text="": shown.append(str(text))
    conversation._item_in_window = lambda item, now, end: True
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()

    module = SimpleNamespace(
        conversation=conversation,
        legacy=SimpleNamespace(_split_lifecycle_duration=lambda parsed: (parsed, None)),
        base=SimpleNamespace(_render_result=lambda *args, **kwargs: None),
        _execute_user=lambda app, parsed, paginate=True: (0, False),
        _run_command_without_render=lambda app, parsed: (0, False, None),
    )

    # Simulate the real conversation_app path: the menu has already been built from
    # one snapshot and then the human selects Upcoming. Before the regression fix,
    # this second _visible_call issued another agenda.startup_snapshot request.
    selected = []

    def home_menu(app, snapshot):
        selected.append(
            conversation._visible_call(
                app,
                "Refreshing Upcoming…",
                lambda: module._read_snapshot(app),
            )
        )
        return "console"

    conversation._home_menu = home_menu
    return module, conversation, selected


def test_one_guided_menu_visit_uses_one_live_snapshot(monkeypatch):
    reads = []
    shown = []
    healthy = _Snapshot()

    def read_snapshot(module, app):
        reads.append("read")
        return healthy

    module, conversation, selected = _module(read_snapshot, shown)
    monkeypatch.setattr(latency_guard, "_read_snapshot", read_snapshot)

    latency_guard.install(module)
    result = conversation._home_menu(SimpleNamespace(), None)

    assert result == "console"
    assert reads == ["read"]
    assert selected == [healthy]


def test_repeated_upcoming_timeout_stays_inside_cli(monkeypatch):
    reads = []
    shown = []

    def read_snapshot(module, app):
        reads.append("read")
        raise UnavailableError("Startup live read exceeded 8s: agenda.startup_snapshot")

    module, conversation, selected = _module(read_snapshot, shown)
    monkeypatch.setattr(latency_guard, "_read_snapshot", read_snapshot)

    latency_guard.install(module)
    result = conversation._home_menu(SimpleNamespace(), None)

    assert result == "console"
    # One attempt to build the menu, one explicit retry because the human selected
    # Upcoming while the menu was already marked unavailable. Neither escapes.
    assert reads == ["read", "read"]
    assert len(selected) == 1
    assert selected[0].warning is not None
    assert any("console is still usable" in line.lower() for line in shown)
    assert any("no Task/Event state was changed" in line for line in shown)
