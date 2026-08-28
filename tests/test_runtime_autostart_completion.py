from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

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
    assert "ExecStart=/example/python -m caldav_assistant.internal.runtime.service" in text
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
