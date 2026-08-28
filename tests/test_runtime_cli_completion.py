from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.runtime.cli import (
    BackgroundActions,
    register_background_cli_command,
)


class Runtime:
    def __init__(self):
        self.running = False
        self.pid = 42
        self.calls = []

    def status(self):
        self.calls.append("status")
        return {
            "status": "running" if self.running else "stopped",
            "pid": self.pid if self.running else None,
            "maintenance_alive": self.running,
        }

    def ensure_running(self):
        self.calls.append("start")
        self.running = True
        return self.status()

    def stop(self):
        self.calls.append("stop")
        was_running = self.running
        self.running = False
        return was_running

    def restart(self):
        self.calls.append("restart")
        self.running = True
        self.pid += 1
        return self.status()


class Autostart:
    def __init__(self):
        self.enabled = False
        self.calls = []

    def is_enabled(self):
        self.calls.append("status")
        return self.enabled

    def enable(self):
        self.calls.append("enable")
        self.enabled = True

    def disable(self, *, stop=True):
        self.calls.append(("disable", stop))
        self.enabled = False


def test_background_actions_cover_status_process_lifecycle_and_autostart():
    runtime = Runtime()
    autostart = Autostart()
    actions = BackgroundActions(runtime, autostart)

    assert "Background service: Stopped" in actions.command("status")
    assert "Background reminders: Off" in actions.command("status")

    started = actions.command("start")
    assert "Background service: Running" in started
    assert "Maintenance: Running" in started
    assert "PID: 42" in started

    restarted = actions.command("restart")
    assert "PID: 43" in restarted

    enabled = actions.command("enable")
    assert autostart.enabled is True
    assert "Background reminders: On" in enabled

    disabled = actions.command("disable")
    assert autostart.enabled is False
    assert runtime.running is False
    assert "Background service: Stopped" in disabled
    assert ("disable", True) in autostart.calls


def test_background_command_is_protected_registry_entry_and_validates_actions():
    commands = CommandService(CommandRegistry())
    runtime = Runtime()
    actions = register_background_cli_command(
        commands,
        runtime,
        autostart=Autostart(),
    )
    assert commands.resolve("background").protected is True
    assert "background restart" in actions.command("help")
    with pytest.raises(ValidationError, match="Unknown background action"):
        actions.command("explode")
    with pytest.raises(ValidationError, match="one action"):
        actions.command("status", "extra")
