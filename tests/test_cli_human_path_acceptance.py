from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli import app as cli_app
from caldav_assistant.internal.cli import monitor_app
from caldav_assistant.internal.cli.actions import EXIT_REPL
from caldav_assistant.internal.cli.navigation import register_navigation_cli_commands
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts import Menu, PromptKit


class ScriptIO:
    """Tiny terminal script: each read is one human key/line decision."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.output: list[str] = []
        self.errors: list[str] = []

    def read(self, prompt: str = "") -> str:
        self.output.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def write(self, value: object = "", end: str = "\n") -> None:
        self.output.append(str(value))

    def error(self, value: object) -> None:
        self.errors.append(str(value))


class InterruptOnSecondCurrentTask:
    """Model Ctrl-C landing in the Session/IPC read after leaving the menu."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_items = []
        self.current_selection = None

    def current_task(self):
        self.calls += 1
        if self.calls == 2:
            raise KeyboardInterrupt
        return None


class CountingSession:
    def __init__(self) -> None:
        self.calls = 0
        self.last_items = []
        self.current_selection = None

    def current_task(self):
        self.calls += 1
        return None


def _guided_app(io: ScriptIO, session: object):
    menu = Menu(io)
    ui = PromptKit(io, menu, temporal=SimpleNamespace())
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=ui, commands=commands, session=session)
    app = SimpleNamespace(
        io=io,
        ctx=ctx,
        commands=commands,
        extensions=None,
        runtime=None,
    )
    register_navigation_cli_commands(commands, ctx)
    return app


def test_exact_human_path_enter_blank_zero_ctrl_c_is_clean():
    """Regression for the terminal sequence reported by a real user.

    REPL Enter opens the guided menu; a second blank Enter is neutral rather than an
    error; 0 leaves the menu; Ctrl-C may land in the following Session/IPC refresh
    and must exit cleanly instead of leaking queue/thread/runtime traceback details.
    """
    io = ScriptIO("", "", "0")
    session = InterruptOnSecondCurrentTask()
    app = _guided_app(io, session)

    code = cli_app.run_repl(app)

    assert code == 130
    assert session.calls == 2
    text = "\n".join(io.output + io.errors)
    assert "CalDAV Assistant" in text
    assert "0. Leave menu" in text
    assert "Invalid choice" not in text
    assert "Traceback" not in text
    assert "queue.py" not in text
    assert "threading.py" not in text


def test_repl_does_not_poll_session_again_before_first_prompt():
    """The prompt itself must not pay for a redundant synchronous Session IPC call."""
    io = ScriptIO("exit")
    session = CountingSession()
    app = _guided_app(io, session)
    app.commands.register_builtin("exit", lambda: EXIT_REPL)

    assert cli_app.run_repl(app) == 0
    assert session.calls == 1


def test_blank_enter_without_default_is_neutral_menu_input():
    io = ScriptIO("", "0")

    assert Menu(io).choose("Pick", ["A"]) is None
    assert not any("Invalid choice" in line for line in io.output)


def test_stable_main_delegates_to_current_foreground_client(monkeypatch):
    monkeypatch.setattr(monitor_app, "run_cli", lambda: 17)
    assert cli_app.main() == 17


def test_stable_main_has_final_keyboard_interrupt_boundary(monkeypatch):
    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(monitor_app, "run_cli", interrupted)
    assert cli_app.main() == 130
