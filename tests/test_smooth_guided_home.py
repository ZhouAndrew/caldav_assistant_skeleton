from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from caldav_assistant.internal.cli import smooth_home


@dataclass(frozen=True)
class _Snapshot:
    name: str


class _UI:
    def __init__(self, selections):
        self.selections = list(selections)
        self.calls = []

    def choose(self, title, items, **kwargs):
        self.calls.append((title, tuple(items)))
        if not self.selections:
            raise AssertionError("unexpected extra menu prompt")
        return self.selections.pop(0)


def _module(selections):
    shown = []
    snapshots = []
    ui = _UI(selections)
    conversation = SimpleNamespace()
    conversation.StartupSnapshot = _Snapshot
    conversation._show = lambda app, value="": shown.append(str(value))
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()

    def home_menu(app, snapshot):
        snapshots.append(snapshot)
        selected = app.ctx.ui.choose(
            "What do you want to do?",
            (
                "Upcoming — next 24h",
                "Choose a Task and start",
                "Task / Event management",
                "Stay in console",
            ),
        )
        if selected == "Upcoming — next 24h":
            conversation._visible_call(
                app,
                "Refreshing Upcoming…",
                lambda: _Snapshot("fresh"),
            )
        return "console"

    conversation._home_menu = home_menu
    module = SimpleNamespace(conversation=conversation)
    app = SimpleNamespace(ctx=SimpleNamespace(ui=ui))
    return module, app, ui, snapshots, shown


def test_read_only_home_action_stays_in_numbered_menu_and_reuses_refreshed_snapshot():
    module, app, ui, snapshots, shown = _module(
        ["Upcoming — next 24h", "Stay in console"]
    )
    initial = _Snapshot("initial")

    smooth_home.install(module)
    result = module.conversation._home_menu(app, initial)

    assert result == "console"
    assert [value.name for value in snapshots] == ["initial", "fresh"]
    assert [call[0] for call in ui.calls] == [
        "What do you want to do?",
        "What do you want to do?",
    ]
    assert shown == []
    # The temporary recorder must not permanently shadow PromptKit.choose.
    assert "choose" not in ui.__dict__


def test_cancelled_or_blocked_guided_start_returns_to_same_numbered_menu():
    module, app, ui, snapshots, shown = _module(
        ["Choose a Task and start", "Stay in console"]
    )
    initial = _Snapshot("initial")

    smooth_home.install(module)
    result = module.conversation._home_menu(app, initial)

    assert result == "console"
    assert snapshots == [initial, initial]
    assert len(ui.calls) == 2
    assert shown == []


def test_state_changing_nested_shell_exits_to_explicit_command_mode_instead_of_reusing_stale_snapshot():
    module, app, ui, snapshots, shown = _module(["Task / Event management"])
    initial = _Snapshot("initial")

    smooth_home.install(module)
    result = module.conversation._home_menu(app, initial)

    assert result == "console"
    assert snapshots == [initial]
    assert len(ui.calls) == 1
    assert any("Returned to the command console" in line for line in shown)


def test_install_is_idempotent():
    module, app, ui, snapshots, shown = _module(["Stay in console"])
    original = module.conversation._home_menu

    smooth_home.install(module)
    installed = module.conversation._home_menu
    smooth_home.install(module)

    assert installed is module.conversation._home_menu
    assert installed is not original
    assert installed(app, _Snapshot("initial")) == "console"
