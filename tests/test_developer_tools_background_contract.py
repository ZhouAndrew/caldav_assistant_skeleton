from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import caldav_assistant

from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def _commands(tmp_path: Path) -> CommandService:
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
    return commands


def test_background_detach_kwargs_cover_posix_and_windows_without_needing_both_runners(tmp_path):
    commands = _commands(tmp_path)
    helper = commands.resolve("run").handler.__globals__["_background_process_kwargs"]
    log_path = tmp_path / "process.log"
    with log_path.open("w+b") as log_handle:
        posix = helper(log_handle, platform_name="posix")
        windows = helper(log_handle, platform_name="nt")

    assert posix["stdin"] is subprocess.DEVNULL
    assert posix["stdout"] is log_handle
    assert posix["stderr"] is subprocess.STDOUT
    assert posix["close_fds"] is True
    assert posix["start_new_session"] is True
    assert "creationflags" not in posix

    expected_flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    assert windows["stdin"] is subprocess.DEVNULL
    assert windows["stdout"] is log_handle
    assert windows["stderr"] is subprocess.STDOUT
    assert windows["close_fds"] is True
    assert windows["creationflags"] == expected_flags
    assert "start_new_session" not in windows


def test_run_background_real_process_writes_the_reported_log(tmp_path):
    commands = _commands(tmp_path)

    result = commands.run(
        "run",
        sys.executable,
        "-c",
        "print('caldav-background-ready', flush=True)",
        "in",
        "background",
    )

    assert "Started in background (PID " in result
    marker = "Output log: "
    assert marker in result
    log_path = Path(result.split(marker, 1)[1].strip())

    text = ""
    for _ in range(40):
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if "caldav-background-ready" in text:
                break
        time.sleep(0.05)

    assert "caldav-background-ready" in text

    # Seeing the flushed line does not prove the detached child has exited. Windows
    # correctly keeps the log locked until the child releases its inherited handle;
    # POSIX permits unlinking an open file. Wait for the real cross-platform lifecycle
    # instead of changing production logging semantics just to make this test portable.
    deadline = time.monotonic() + 2.0
    while True:
        try:
            log_path.unlink(missing_ok=True)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
