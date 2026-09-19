from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from caldav_assistant.internal.cli import smooth_home


@dataclass(frozen=True)
class Snapshot:
    name: str


class IO:
    def __init__(self, values=None):
        self.values = list(values or ["1"])
        self.commands = []

    def read(self, prompt=""):
        if not self.values:
            raise AssertionError("unexpected extra input read")
        return self.values.pop(0)


class UI:
    def __init__(self):
        self.fallback_calls = 0

    def choose(self, title, items, **kwargs):
        self.fallback_calls += 1
        # The numeric selection is injected before this fallback. On the next home
        # iteration leave menu mode cleanly.
        return "Stay in console"


def test_bare_console_one_uses_same_startup_snapshot_and_visible_home_number():
    ui = UI()
    io = IO()
    selected = []
    snapshots = []
    conversation = SimpleNamespace()
    conversation.StartupSnapshot = Snapshot
    conversation._show = lambda app, value="": None
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()

    def home_menu(app, snapshot):
        snapshots.append(snapshot)
        choice = app.ctx.ui.choose(
            "What do you want to do?",
            (
                "Upcoming — next 24h",
                "Choose a Task and start",
                "Stay in console",
            ),
        )
        selected.append(choice)
        return "console"

    def console(app, snapshot):
        raw = app.io.read("> ")
        if raw != "":
            app.io.commands.append(raw)
            return 1, "console"
        return 0, conversation._home_menu(app, snapshot)

    conversation._home_menu = home_menu
    conversation._console = console
    module = SimpleNamespace(conversation=conversation)
    app = SimpleNamespace(ctx=SimpleNamespace(ui=ui), io=io)
    startup = Snapshot("startup")

    smooth_home.install(module)
    result = conversation._console(app, startup)

    assert result == (0, "console")
    # The number never reaches the command path.
    assert io.commands == []
    # Stable home ordering puts the primary work action in slot 1.
    assert selected[0] == "Choose a Task and start"
    assert selected[-1] == "Stay in console"
    # Most importantly, numeric input reused the exact startup snapshot rather than
    # constructing a fresh/None home state.
    assert snapshots == [startup, startup]
    # Temporary wrappers must not shadow the normal IO/PromptKit methods afterwards.
    assert "read" not in io.__dict__
    assert "choose" not in ui.__dict__


def test_enter_then_menu_one_is_not_stolen_by_top_level_numeric_wrapper():
    """Regression for the real PTY failure: Enter -> home -> 1 must stay PromptKit input."""
    io = IO(["", "1", "0"])
    selected = []
    snapshots = []
    conversation = SimpleNamespace()
    conversation.StartupSnapshot = Snapshot
    conversation._show = lambda app, value="": None
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()

    class PromptLikeUI:
        def choose(self, title, items, **kwargs):
            raw = io.read("> ").strip()
            if raw == "0":
                return None
            number = int(raw)
            return tuple(items)[number - 1]

    ui = PromptLikeUI()

    def home_menu(app, snapshot):
        snapshots.append(snapshot)
        choice = app.ctx.ui.choose(
            "What do you want to do?",
            (
                "Upcoming — next 24h",
                "Choose a Task and start",
                "Stay in console",
            ),
        )
        selected.append(choice)
        return "console"

    def console(app, snapshot):
        raw = app.io.read("> ")
        if raw != "":
            app.io.commands.append(raw)
            return 1, "console"
        return 0, conversation._home_menu(app, snapshot)

    conversation._home_menu = home_menu
    conversation._console = console
    module = SimpleNamespace(conversation=conversation)
    app = SimpleNamespace(ctx=SimpleNamespace(ui=ui), io=io)
    startup = Snapshot("startup")

    smooth_home.install(module)
    result = conversation._console(app, startup)

    assert result == (0, "console")
    assert io.commands == []
    assert selected == ["Choose a Task and start", None]
    assert snapshots == [startup, startup]
