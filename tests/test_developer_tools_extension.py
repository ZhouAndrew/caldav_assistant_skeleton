from __future__ import annotations

from pathlib import Path
import os
import subprocess
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


def test_developer_tools_register_clear_shell_and_run(tmp_path, capsys):
    manager, commands = make_manager(tmp_path)

    clear_entry = commands.resolve("clear")
    shell_entry = commands.resolve("shell")
    run_entry = commands.resolve("run")

    assert clear_entry.source == "extension:developer_tools"
    assert shell_entry.source == "extension:developer_tools"
    assert run_entry.source == "extension:developer_tools"
    assert commands.resolve("cls").name == "clear"
    assert commands.resolve("sh").name == "shell"
    assert manager.get("developer_tools").status == "loaded"

    commands.run("clear")
    assert capsys.readouterr().out == "\x1b[2J\x1b[H"


def test_shell_keeps_original_foreground_external_process_contract(tmp_path):
    _, commands = make_manager(tmp_path)

    result = commands.run(
        "shell",
        sys.executable,
        "-c",
        "import sys; sys.exit(7)",
    )

    assert result == 7


def test_shell_reports_missing_program_and_explains_shell_boundary(tmp_path):
    _, commands = make_manager(tmp_path)

    with pytest.raises(ValueError, match="External command not found") as exc:
        commands.run("shell", "caldav-assistant-command-that-does-not-exist-12345")

    assert "shell built-in" in str(exc.value)
    assert "run bash -lc" in str(exc.value)


def test_run_foreground_reports_exit_code_and_uses_subprocess_run(tmp_path, monkeypatch):
    _, commands = make_manager(tmp_path)
    calls = []

    class Result:
        returncode = 9

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = commands.run("run", "tool", "arg")

    assert result == "Command exited with code 9."
    assert calls == [(["tool", "arg"], {"check": False})]


def test_run_human_background_suffix_detaches_input_preserves_output_log_and_returns_pid(
    tmp_path,
    monkeypatch,
):
    _, commands = make_manager(tmp_path)
    calls = []
    log_path = tmp_path / "background.log"
    log_handle = log_path.open("w+b")

    class Process:
        pid = 43210

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return Process()

    monkeypatch.setattr(
        "caldav_assistant.builtin_extensions.developer_tools._background_log",
        lambda: (log_handle, log_path),
    )
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = commands.run("run", "python", "worker.py", "in", "background")

    assert "Started in background (PID 43210): python worker.py" in result
    assert f"Output log: {log_path}" in result
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["python", "worker.py"]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is log_handle
    assert kwargs["stderr"] is subprocess.STDOUT
    assert kwargs["close_fds"] is True
    assert log_handle.closed is True
    if os.name == "nt":
        expected = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        assert kwargs["creationflags"] == expected
        assert "start_new_session" not in kwargs
    else:
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs


def test_run_background_has_script_friendly_flag_forms(tmp_path, monkeypatch):
    _, commands = make_manager(tmp_path)

    class Process:
        pid = 123

    seen = []

    def fake_log():
        path = tmp_path / f"bg-{len(seen)}.log"
        return path.open("w+b"), path

    monkeypatch.setattr(
        "caldav_assistant.builtin_extensions.developer_tools._background_log",
        fake_log,
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kwargs: seen.append(list(argv)) or Process(),
    )

    assert "PID 123" in commands.run("run", "--background", "tool", "a")
    assert "PID 123" in commands.run("run", "-b", "tool", "b")
    assert seen == [["tool", "a"], ["tool", "b"]]


def test_run_rejects_empty_or_background_without_command(tmp_path):
    _, commands = make_manager(tmp_path)

    with pytest.raises(ValueError, match="run requires an external command"):
        commands.run("run")
    with pytest.raises(ValueError, match="Background mode requires"):
        commands.run("run", "in", "background")
    with pytest.raises(ValueError, match="Background mode requires"):
        commands.run("run", "--background")
