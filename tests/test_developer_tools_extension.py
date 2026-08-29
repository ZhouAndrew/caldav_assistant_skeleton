from __future__ import annotations

from pathlib import Path
import sys

import caldav_assistant
import pytest

from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def make_manager(tmp_path: Path):
    commands = CommandService(CommandRegistry())
    bundled = Path(caldav_assistant.__file__).resolve().parent / "builtin_extensions"
    manager = ExtensionManager(
        commands,
        HookRegistry(),
        FakeSettings(),
        root=tmp_path / "user-extensions",
        bundled_root=bundled,
        default_enabled=("developer_tools",),
    )
    manager.load_enabled()
    return manager, commands


def test_developer_tools_register_clear_and_shell_aliases(tmp_path, capsys):
    manager, commands = make_manager(tmp_path)

    clear_entry = commands.resolve("clear")
    shell_entry = commands.resolve("shell")

    assert clear_entry.source == "extension:developer_tools"
    assert shell_entry.source == "extension:developer_tools"
    assert commands.resolve("cls").name == "clear"
    assert commands.resolve("sh").name == "shell"
    assert manager.get("developer_tools").status == "loaded"

    commands.run("clear")
    assert capsys.readouterr().out == "\x1b[2J\x1b[H"


def test_shell_runs_foreground_external_process_and_returns_exit_code(tmp_path):
    _, commands = make_manager(tmp_path)

    result = commands.run(
        "shell",
        sys.executable,
        "-c",
        "import sys; sys.exit(7)",
    )

    assert result == 7


def test_shell_reports_missing_program_without_using_shell_true(tmp_path):
    _, commands = make_manager(tmp_path)

    with pytest.raises(ValueError, match="External command not found"):
        commands.run("shell", "caldav-assistant-command-that-does-not-exist-12345")
