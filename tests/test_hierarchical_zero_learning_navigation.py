from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from caldav_assistant.builtin_extensions.software_intro import _fallback_for
from caldav_assistant.internal.cli.actions import EXIT_REPL
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.cli.navigation import NavigationActions
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts.kit import PromptKit
from caldav_assistant.internal.prompts.menu import Menu


class ScriptIO:
    def __init__(self, lines=()):
        self.lines = deque(str(item) for item in lines)
        self.pending = deque()
        self.out: list[str] = []
        self.err: list[str] = []

    def read(self, prompt=""):
        if self.pending:
            return self.pending.popleft()
        if self.lines:
            return self.lines.popleft()
        raise EOFError

    def push_line(self, value):
        self.pending.appendleft(str(value))

    def write(self, value="", **kwargs):
        self.out.append(str(value))

    def error(self, value):
        self.err.append(str(value))


def prompt_ui(io: ScriptIO):
    return PromptKit(io, Menu(io), SimpleNamespace())


def test_navigation_has_real_stack_breadcrumb_and_one_level_back():
    # Root -> Manage -> Tasks -> back -> Manage -> back -> Root -> Agenda -> Today.
    io = ScriptIO(["4", "2", "0", "0", "1", "1"])
    ui = prompt_ui(io)
    commands = CommandService(CommandRegistry())
    commands.register_builtin("today", lambda: "TODAY")
    ctx = SimpleNamespace(ui=ui, commands=commands)

    result = NavigationActions(ctx).menu()

    assert result == "TODAY"
    output = "\n".join(io.out)
    assert "CalDAV Assistant > Manage > Tasks" in output
    assert "0. Back to Manage" in output
    # Returning from Tasks did not close navigation: Manage and root were rendered again.
    assert output.count("CalDAV Assistant > Manage") >= 2
    assert output.count("CalDAV Assistant") >= 4


def test_navigation_reuses_shared_menu_and_can_release_direct_command_to_repl():
    io = ScriptIO(["4", "today"])
    ui = prompt_ui(io)
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=ui, commands=commands)

    result = NavigationActions(ctx).menu()

    assert result is None
    # The navigation layer did not parse or execute the command; it handed the exact
    # line back to the normal terminal input path.
    assert io.read() == "today"
    assert "CalDAV Assistant > Manage" in "\n".join(io.out)


def test_shared_menu_supports_contextual_back_label_and_unmatched_callback():
    io = ScriptIO(["run something"])
    menu = Menu(io)
    released = []

    result = menu.choose(
        "Root > Child",
        ("One", "Two"),
        searchable=False,
        back_label="Back to Root",
        on_unmatched=lambda raw: released.append(raw) or "released",
    )

    assert result == "released"
    assert released == ["run something"]
    assert "0. Back to Root" in "\n".join(io.out)


def test_empty_repl_line_opens_guided_menu_when_available():
    io = ScriptIO(["", "exit"])
    ui = SimpleNamespace(show=lambda value: io.write(value))
    commands = CommandService(CommandRegistry())
    commands.register_builtin("menu", lambda: "GUIDED MENU")
    commands.register_builtin("exit", lambda: EXIT_REPL)
    app = SimpleNamespace(
        io=io,
        ctx=SimpleNamespace(ui=ui, commands=commands),
        commands=commands,
        extensions=None,
        runtime=None,
    )

    assert run_repl(app) == 0
    assert "GUIDED MENU" in io.out
    assert any("Press Enter for the guided menu" in line for line in io.out)


def test_startup_intro_teaches_an_action_not_a_command_vocabulary():
    class Settings:
        def get(self, key, default=None):
            values = {
                "ui.locale": "en",
                "caldav.base_url": "https://dav.example/",
                "caldav.task_collection_url": "https://dav.example/tasks/",
            }
            return values.get(key, default)

    text = _fallback_for(SimpleNamespace(settings=Settings()))

    assert "press Enter" in text
    assert "choose with numbers" in text
    assert "Commands are optional shortcuts" in text
    assert "today / next" not in text
