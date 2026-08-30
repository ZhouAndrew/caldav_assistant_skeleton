from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.cli import versioned_entrypoint
from caldav_assistant.internal.runtime.build_identity import RUNTIME_BUILD_IDENTITY
from caldav_assistant.internal.runtime.versioned_observable_service import (
    VersionedObservableAssistantService,
)


class FakeRuntime:
    def __init__(self, statuses, *, restart_error=None):
        self.statuses = list(statuses)
        self.restart_error = restart_error
        self.restart_calls = []

    def status(self):
        if len(self.statuses) > 1:
            return dict(self.statuses.pop(0))
        return dict(self.statuses[0])

    def restart(self, *, timeout=5.0):
        self.restart_calls.append(timeout)
        if self.restart_error is not None:
            raise self.restart_error
        if len(self.statuses) > 1:
            self.statuses.pop(0)
        return dict(self.statuses[0])


class FakeUI:
    def __init__(self):
        self.messages = []

    def show(self, value):
        self.messages.append(str(value))


def app_for(runtime):
    return SimpleNamespace(runtime=runtime, ctx=SimpleNamespace(ui=FakeUI()), io=None)


def running(identity=None, pid=10):
    value = {"status": "running", "pid": pid}
    if identity is not None:
        value["runtime_identity"] = identity
    return value


def test_current_daemon_is_left_running_without_restart():
    runtime = FakeRuntime([running(RUNTIME_BUILD_IDENTITY)])
    app = app_for(runtime)

    assert versioned_entrypoint.ensure_current_background(app) is False
    assert runtime.restart_calls == []
    assert app.ctx.ui.messages == []


def test_pre_handshake_daemon_without_identity_is_restarted_before_use():
    runtime = FakeRuntime(
        [
            running(pid=41),
            running(RUNTIME_BUILD_IDENTITY, pid=42),
        ]
    )
    app = app_for(runtime)

    assert versioned_entrypoint.ensure_current_background(app) is True
    assert runtime.restart_calls == [5.0]
    assert "restarted the stale daemon automatically" in app.ctx.ui.messages[-1]
    assert "PID 41 -> 42" in app.ctx.ui.messages[-1]


def test_mismatched_source_identity_is_restarted_before_use():
    runtime = FakeRuntime(
        [
            running("1.0.0+src.old", pid=50),
            running(RUNTIME_BUILD_IDENTITY, pid=51),
        ]
    )
    app = app_for(runtime)

    assert versioned_entrypoint.ensure_current_background(app) is True
    assert runtime.restart_calls == [5.0]


def test_stopped_daemon_is_not_started_just_for_version_check():
    runtime = FakeRuntime([{"status": "stopped", "pid": None}])
    app = app_for(runtime)

    assert versioned_entrypoint.ensure_current_background(app) is False
    assert runtime.restart_calls == []


def test_failed_stale_restart_blocks_business_operations():
    runtime = FakeRuntime(
        [running("legacy", pid=60)],
        restart_error=RuntimeError("shutdown failed"),
    )
    app = app_for(runtime)

    with pytest.raises(UnavailableError, match="older code"):
        versioned_entrypoint.ensure_current_background(app)


def test_restart_that_still_reports_stale_code_is_rejected():
    runtime = FakeRuntime(
        [
            running("legacy-a", pid=70),
            running("legacy-b", pid=71),
        ]
    )
    app = app_for(runtime)

    with pytest.raises(UnavailableError, match="still does not match"):
        versioned_entrypoint.ensure_current_background(app)


def test_background_admin_commands_do_not_mutate_runtime(monkeypatch):
    runtime = FakeRuntime([running("legacy", pid=80)])
    app = app_for(runtime)
    calls = []

    monkeypatch.setattr(
        versioned_entrypoint.monitor_app,
        "run_cli",
        lambda argv, app=None: calls.append((list(argv), app)) or 0,
    )

    assert versioned_entrypoint.run_cli(["background", "status"], app=app) == 0
    assert runtime.restart_calls == []
    assert calls == [(["background", "status"], app)]


def test_normal_cli_command_upgrades_stale_runtime_before_dispatch(monkeypatch):
    runtime = FakeRuntime(
        [
            running("legacy", pid=90),
            running(RUNTIME_BUILD_IDENTITY, pid=91),
        ]
    )
    app = app_for(runtime)
    observed = []

    def run_cli(argv, app=None):
        observed.append((list(argv), len(runtime.restart_calls)))
        return 0

    monkeypatch.setattr(versioned_entrypoint.monitor_app, "run_cli", run_cli)

    assert versioned_entrypoint.run_cli(["pause"], app=app) == 0
    assert observed == [(["pause"], 1)]


def test_versioned_service_exposes_process_identity_on_ping_and_status():
    class FakeIPC:
        def close(self):
            return None

    service = VersionedObservableAssistantService(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        FakeIPC(),
        SimpleNamespace(handle=lambda method, payload: None),
    )

    ping = service._handle_request("runtime.ping", {})
    status = service.status()

    assert ping["status"] == "ok"
    assert ping["runtime_identity"] == RUNTIME_BUILD_IDENTITY
    assert status["runtime_identity"] == RUNTIME_BUILD_IDENTITY
