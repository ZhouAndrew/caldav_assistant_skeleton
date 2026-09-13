from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli import smooth_home


class UI:
    def __init__(self):
        self.fallback_calls = 0

    def choose(self, title, items, **kwargs):
        self.fallback_calls += 1
        # After the seeded numeric choice has executed, leave menu mode cleanly.
        return "Stay in console"


def test_bare_console_one_selects_visible_home_item_instead_of_command_registry():
    ui = UI()
    selected = []
    unsupported = []
    conversation = SimpleNamespace()
    conversation.StartupSnapshot = type("Snapshot", (), {})
    conversation._show = lambda app, value="": None
    conversation._visible_call = lambda app, label, fn, *args, **kwargs: fn()

    def home_menu(app, snapshot):
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

    conversation._home_menu = home_menu

    def old_execute(app, parsed, *, paginate=True):
        unsupported.append(parsed.raw)
        return 1, False

    module = SimpleNamespace(
        conversation=conversation,
        _execute_user=old_execute,
    )
    app = SimpleNamespace(ctx=SimpleNamespace(ui=ui))
    parsed = SimpleNamespace(raw="1", args=())

    smooth_home.install(module)
    code, should_exit = module._execute_user(app, parsed)

    assert (code, should_exit) == (0, False)
    assert unsupported == []
    # Stable home ordering puts the primary work action in slot 1.
    assert selected[0] == "Choose a Task and start"
    assert selected[-1] == "Stay in console"
