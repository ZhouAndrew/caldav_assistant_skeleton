from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli import monitor_app


class FakeIO:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.out = []

    def read(self, prompt=""):
        return next(self.lines)

    def write(self, value=""):
        self.out.append(str(value))


class Session:
    current_selection = None

    def __init__(self, current=None):
        self.current = current

    def current_task(self):
        return self.current


def make_app(lines, *, current=None):
    io = FakeIO(lines)
    ui = SimpleNamespace(show=io.write)
    return SimpleNamespace(
        io=io,
        ctx=SimpleNamespace(ui=ui, session=Session(current)),
    )


def test_console_opened_from_monitor_stays_for_multiple_other_commands(monkeypatch):
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    app = make_app(["today", "history", "monitor"], current=task)
    calls = []

    def execute(app, parsed, *, paginate=True):
        calls.append(parsed.name)
        return 0, False

    monkeypatch.setattr(monitor_app, "_execute_visible", execute)

    code, action = monitor_app._console(app)

    assert code == 0
    assert action == "monitor"
    assert calls == ["today", "history"]


def test_idle_console_enters_monitor_after_command_creates_target(monkeypatch):
    app = make_app(["next"])
    selected = Task(id="t2", summary="Physics", status="NEEDS-ACTION")

    def execute(app, parsed, *, paginate=True):
        app.ctx.session.current_selection = selected
        return 0, False

    monkeypatch.setattr(monitor_app, "_execute_visible", execute)

    code, action = monitor_app._console(app)

    assert code == 0
    assert action == "monitor"
    assert app.ctx.session.current_selection is selected
