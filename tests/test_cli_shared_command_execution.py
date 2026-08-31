from types import SimpleNamespace

from caldav_assistant.internal.cli import app as cli_app
from caldav_assistant.internal.cli.actions import EXIT_REPL


class FakeUI:
    def __init__(self):
        self.values = []

    def show(self, value):
        self.values.append(str(value))


class FakeIO:
    def __init__(self):
        self.errors = []

    def error(self, value):
        self.errors.append(str(value))


class FakeCommands:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def resolve(self, name):
        return SimpleNamespace(name=name)

    def run(self, name, *args):
        self.calls.append((name, args))
        if self.error is not None:
            raise self.error
        return self.result


def make_app(*, result=None, error=None):
    ui = FakeUI()
    io = FakeIO()
    commands = FakeCommands(result=result, error=error)
    ctx = SimpleNamespace(ui=ui, session=SimpleNamespace(last_items=[], current_selection=None))
    return SimpleNamespace(ctx=ctx, io=io, commands=commands, extensions=None), ui, io, commands


def test_execute_command_defers_successful_result_rendering():
    app, ui, io, commands = make_app(result="shared-result")
    parsed = cli_app.ParsedCommand(raw="demo", name="demo", args=())

    outcome = cli_app.execute_command(app, parsed)

    assert outcome.exit_code == 0
    assert outcome.should_exit is False
    assert outcome.result == "shared-result"
    assert commands.calls == [("demo", ())]
    assert ui.values == []
    assert io.errors == []


def test_execute_wrapper_preserves_immediate_rendering():
    app, ui, io, _ = make_app(result="shared-result")
    parsed = cli_app.ParsedCommand(raw="demo", name="demo", args=())

    code, should_exit = cli_app._execute(app, parsed)

    assert code == 0
    assert should_exit is False
    assert "shared-result" in "\n".join(ui.values)
    assert io.errors == []


def test_execute_command_preserves_validation_error_semantics():
    app, ui, io, _ = make_app(error=ValueError("bad input"))
    parsed = cli_app.ParsedCommand(raw="demo", name="demo", args=())

    outcome = cli_app.execute_command(app, parsed)

    assert outcome.exit_code == 2
    assert outcome.should_exit is False
    assert outcome.result is None
    assert ui.values == []
    assert any("Invalid input: bad input" in value for value in io.errors)


def test_execute_command_preserves_exit_sentinel_semantics():
    app, ui, io, _ = make_app(result=EXIT_REPL)
    parsed = cli_app.ParsedCommand(raw="exit", name="exit", args=())

    outcome = cli_app.execute_command(app, parsed)

    assert outcome.exit_code == 0
    assert outcome.should_exit is True
    assert outcome.result is None
    assert ui.values == []
    assert io.errors == []
