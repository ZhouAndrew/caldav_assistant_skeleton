from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.runtime.build_identity import RUNTIME_BUILD_IDENTITY
from caldav_assistant.internal.runtime.proxies import RemoteTasksAPI


class Runtime:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []
        self.restart_calls = 0

    def bind_domain(self, kind, service):
        return None

    def status(self):
        if len(self.statuses) > 1:
            return dict(self.statuses.pop(0))
        return dict(self.statuses[0])

    def restart(self, timeout=5.0):
        self.restart_calls += 1
        if len(self.statuses) > 1:
            self.statuses.pop(0)
        return dict(self.statuses[0])

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return SimpleNamespace(success=True)


def running(identity=None):
    value = {"status": "running", "pid": 1}
    if identity is not None:
        value["runtime_identity"] = identity
    return value


def test_task_operation_restarts_pre_handshake_daemon_before_dispatch():
    runtime = Runtime([running(), running(RUNTIME_BUILD_IDENTITY)])
    tasks = RemoteTasksAPI(runtime)

    result = tasks.pause("anki")

    assert result.success is True
    assert runtime.restart_calls == 1
    assert runtime.calls == [("tasks.pause", {"task": "anki"})]


def test_task_operation_restarts_mismatched_daemon_before_dispatch():
    runtime = Runtime(
        [
            running("1.0.0+src.old"),
            running(RUNTIME_BUILD_IDENTITY),
        ]
    )
    tasks = RemoteTasksAPI(runtime)

    tasks.start("anki")

    assert runtime.restart_calls == 1
    assert runtime.calls[0][0] == "tasks.start"


def test_current_daemon_is_verified_once_for_multiple_operations():
    runtime = Runtime([running(RUNTIME_BUILD_IDENTITY)])
    tasks = RemoteTasksAPI(runtime)

    tasks.start("anki")
    tasks.pause("anki")

    assert runtime.restart_calls == 0
    assert [method for method, _ in runtime.calls] == ["tasks.start", "tasks.pause"]
    assert runtime._caldav_assistant_generation_verified is True


def test_test_double_without_status_keeps_existing_proxy_contract():
    class MinimalRuntime:
        def __init__(self):
            self.calls = []
        def bind_domain(self, kind, service):
            return None
        def call(self, method, **payload):
            self.calls.append((method, payload))
            return "ok"

    runtime = MinimalRuntime()
    tasks = RemoteTasksAPI(runtime)

    assert tasks.pause("anki") == "ok"
    assert runtime.calls == [("tasks.pause", {"task": "anki"})]


def test_stale_daemon_that_cannot_restart_blocks_task_operation():
    class NoRestartRuntime(Runtime):
        restart = None

    runtime = NoRestartRuntime([running("legacy")])
    tasks = RemoteTasksAPI(runtime)

    with pytest.raises(UnavailableError, match="cannot restart"):
        tasks.pause("anki")

    assert runtime.calls == []
