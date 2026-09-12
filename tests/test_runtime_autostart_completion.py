from __future__ import annotations

import plistlib
from types import SimpleNamespace
import sys

import pytest

from caldav_assistant.internal.runtime import autostart as autostart_module
from caldav_assistant.internal.runtime.autostart import AutostartManager


def test_linux_user_autostart_uses_current_python_and_systemd_user(tmp_path, monkeypatch):
    unit = tmp_path / "caldav-assistant.service"
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        AutostartManager,
        "_systemd_path",
        staticmethod(lambda: unit),
    )
    manager = AutostartManager(python="/example/python", runner=runner)
    manager.enable()

    text = unit.read_text()
    assert (
        "ExecStart=/example/python -m "
        "caldav_assistant.internal.runtime.versioned_observable_service"
    ) in text
    assert "Restart=on-failure" in text
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert [
        "systemctl",
        "--user",
        "enable",
        "--now",
        unit.name,
    ] in calls
    assert manager.is_enabled() is True
    assert manager.status()["enabled"] is True

    manager.disable(stop=True)
    assert not unit.exists()
    assert [
        "systemctl",
        "--user",
        "disable",
        "--now",
        unit.name,
    ] in calls


def test_autostart_command_matches_production_versioned_service_entrypoint():
    manager = AutostartManager(python="/example/python")
    assert manager.command == [
        "/example/python",
        "-m",
        "caldav_assistant.internal.runtime.versioned_observable_service",
    ]


def test_macos_autostart_restarts_failures_but_allows_clean_stop(tmp_path, monkeypatch):
    agent = tmp_path / "org.caldav-assistant.service.plist"
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        AutostartManager,
        "_launchd_path",
        staticmethod(lambda: agent),
    )
    # Windows does not expose os.getuid; make this cross-platform even though we
    # intentionally exercise the macOS branch in the Windows pytest matrix too.
    monkeypatch.setattr(autostart_module.os, "getuid", lambda: 501, raising=False)

    manager = AutostartManager(python="/example/python", runner=runner)
    manager.enable()

    with agent.open("rb") as stream:
        payload = plistlib.load(stream)
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProgramArguments"] == manager.command
    assert ["launchctl", "bootstrap", "gui/501", str(agent)] in calls


def test_linux_autostart_does_not_report_unit_file_as_enabled_when_systemd_rejects_it(
    tmp_path,
    monkeypatch,
):
    unit = tmp_path / "caldav-assistant.service"

    def runner(args, **kwargs):
        if "is-enabled" in args:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        AutostartManager,
        "_systemd_path",
        staticmethod(lambda: unit),
    )
    unit.write_text("placeholder")
    manager = AutostartManager(runner=runner)
    assert manager.is_enabled() is False


def test_linux_autostart_enable_surfaces_systemd_failure(tmp_path, monkeypatch):
    unit = tmp_path / "caldav-assistant.service"

    def runner(args, **kwargs):
        return SimpleNamespace(returncode=1 if "enable" in args else 0)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        AutostartManager,
        "_systemd_path",
        staticmethod(lambda: unit),
    )
    manager = AutostartManager(runner=runner)
    with pytest.raises(RuntimeError, match="Autostart command failed"):
        manager.enable()
