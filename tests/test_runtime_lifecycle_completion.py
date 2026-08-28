from __future__ import annotations

from threading import Event
from types import SimpleNamespace
import os
import stat

import pytest

from caldav_assistant.api.v1.errors import UnavailableError, ValidationError
from caldav_assistant.internal.runtime.client import RuntimeClient
from caldav_assistant.internal.runtime.ipc import (
    IPCRemoteError,
    IPCUnavailableError,
    load_or_create_authkey,
    runtime_state_dir,
)
from caldav_assistant.internal.runtime.service import AssistantService


class FakeSync:
    def incremental_sync(self):
        return None


class FakeReminders:
    def process_due(self):
        return None


class FakeWordPress:
    def flush(self):
        return None


class FakeIPCServer:
    def close(self):
        return None


class FakeDispatcher:
    def handle(self, method, payload):
        return {"method": method, "payload": payload}


class BrokenDelayScheduler:
    def monotonic(self):
        return 0.0

    def reminder_delay(self, reminders, *, max_delay):
        raise UnavailableError("CalDAV not configured")

    def wait(self, seconds, stop_event):
        stop_event.set()
        return True


def make_service(scheduler=None):
    return AssistantService(
        FakeSync(),
        FakeReminders(),
        FakeWordPress(),
        FakeIPCServer(),
        FakeDispatcher(),
        scheduler or BrokenDelayScheduler(),
        max_idle=0.1,
    )


def test_scheduler_next_due_failure_is_recorded_and_falls_back():
    service = make_service()
    assert service._reminder_delay() == pytest.approx(0.1)
    assert "reminders.next_due" in service.status()["last_errors"]


def test_shutdown_route_acknowledges_before_stopping(monkeypatch):
    service = make_service()
    calls = []
    monkeypatch.setattr(service, "stop", lambda: calls.append("stop"))

    class ImmediateTimer:
        daemon = False
        def __init__(self, delay, target): self.target = target
        def start(self): self.target()

    monkeypatch.setattr("caldav_assistant.internal.runtime.service.Timer", ImmediateTimer)
    result = service._handle_request("runtime.shutdown", {})
    assert result["status"] == "stopping"
    assert calls == ["stop"]


def test_runtime_client_lifecycle_does_not_start_for_status_or_stop():
    state = {"ready": False, "launches": 0}

    class IPC:
        def call(self, method, payload):
            if not state["ready"]:
                raise IPCUnavailableError("offline")
            if method == "runtime.ping": return {"status": "ok", "pid": 10}
            if method == "runtime.status": return {"status": "running", "pid": 10}
            if method == "runtime.shutdown": state["ready"] = False; return {"status": "stopping"}
            return None

    def launch():
        state["launches"] += 1
        state["ready"] = True

    client = RuntimeClient(IPC(), launch, startup_timeout=0.2, poll_interval=0.01)
    assert client.status()["status"] == "stopped"
    assert client.stop() is False
    assert state["launches"] == 0

    assert client.ensure_running()["status"] == "running"
    assert state["launches"] == 1
    assert client.stop(timeout=0.2) is True
    assert client.status()["status"] == "stopped"

    assert client.restart(timeout=0.2)["status"] == "running"
    assert state["launches"] == 2


def test_stop_waits_for_process_launched_by_same_client_to_exit():
    state = {"ready": False, "shutdown": False, "polls_after_shutdown": 0}

    class Process:
        def poll(self):
            if not state["shutdown"]:
                return None
            state["polls_after_shutdown"] += 1
            return 0 if state["polls_after_shutdown"] >= 3 else None

    process = Process()

    class IPC:
        def call(self, method, payload):
            if not state["ready"]:
                raise IPCUnavailableError("offline")
            if method == "runtime.ping":
                return {"status": "ok", "pid": 11}
            if method == "runtime.status":
                return {"status": "running", "pid": 11}
            if method == "runtime.shutdown":
                state["shutdown"] = True
                state["ready"] = False
                return {"status": "stopping", "pid": 11}
            return None

    def launch():
        state["ready"] = True
        return process

    client = RuntimeClient(
        IPC(),
        launch,
        startup_timeout=0.5,
        poll_interval=0.01,
    )
    assert client.ensure_running()["status"] == "running"
    assert client.stop(timeout=0.5) is True
    assert state["polls_after_shutdown"] >= 3
    assert client._launched_process is None


def test_remote_error_after_autostart_is_still_mapped_to_public_error():
    state = {"ready": False}

    class IPC:
        def call(self, method, payload):
            if not state["ready"]:
                raise IPCUnavailableError("offline")
            if method == "runtime.ping": return {"status": "ok"}
            raise IPCRemoteError(
                "ValidationError",
                "bad title",
                module="caldav_assistant.api.v1.errors",
            )

    def launch(): state["ready"] = True

    client = RuntimeClient(IPC(), launch, startup_timeout=0.2, poll_interval=0.01)
    with pytest.raises(ValidationError, match="bad title"):
        client.call("tasks.create", summary="")


def test_blocking_probe_obeys_startup_deadline_instead_of_request_timeout():
    import time
    class IPC:
        def call(self, method, payload):
            time.sleep(0.5)
            raise IPCUnavailableError("offline")

    client = RuntimeClient(
        IPC(), lambda: None,
        request_timeout=5.0,
        startup_timeout=0.12,
        poll_interval=0.01,
    )
    started = time.monotonic()
    with pytest.raises(UnavailableError):
        client.ensure_running()
    assert time.monotonic() - started < 0.8


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_runtime_directory_and_auth_key_are_private_and_stable(tmp_path):
    directory = runtime_state_dir(tmp_path / "runtime")
    first = load_or_create_authkey(directory)
    second = load_or_create_authkey(directory)
    assert first == second and len(first) >= 16
    assert stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE((directory / "ipc.auth").stat().st_mode) & 0o077 == 0


def test_auth_key_concurrent_creation_converges_on_one_value(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    directory = tmp_path / "runtime-race"
    barrier = Barrier(8)

    def load():
        barrier.wait()
        return load_or_create_authkey(directory)

    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: load(), range(8)))

    assert len(set(keys)) == 1
    assert len(keys[0]) >= 16


def test_maintenance_loop_recovers_from_scheduler_orchestration_failure():
    class RecoveringScheduler:
        def __init__(self):
            self.monotonic_calls = 0

        def monotonic(self):
            self.monotonic_calls += 1
            if self.monotonic_calls == 1:
                raise RuntimeError("clock failed once")
            return 0.0

        def reminder_delay(self, reminders, *, max_delay):
            return max_delay

        def wait(self, seconds, stop_event):
            stop_event.set()
            return True

    scheduler = RecoveringScheduler()
    service = make_service(scheduler)
    service._maintenance_loop()
    assert scheduler.monotonic_calls >= 2


def test_losing_ipc_singleton_never_starts_maintenance():
    from caldav_assistant.internal.runtime.ipc import IPCAlreadyRunningError

    class LosingIPC:
        def __init__(self):
            self.ready_callbacks = 0

        def serve_forever(self, handler, stop_event, *, on_ready=None):
            assert callable(on_ready)
            raise IPCAlreadyRunningError("already running")

        def close(self):
            return None

    ipc = LosingIPC()
    service = AssistantService(
        FakeSync(),
        FakeReminders(),
        FakeWordPress(),
        ipc,
        FakeDispatcher(),
        BrokenDelayScheduler(),
        max_idle=0.1,
    )
    with pytest.raises(IPCAlreadyRunningError):
        service.run_forever()
    assert service.running is False
    assert service._maintenance_thread is None


def test_blocking_sync_does_not_starve_wordpress_or_reminder_processing():
    from threading import Event
    from time import monotonic, sleep

    sync_started = Event()
    release_sync = Event()
    wordpress_flushed = Event()
    reminders_processed = Event()

    class BlockingSync:
        def incremental_sync(self):
            sync_started.set()
            release_sync.wait(2.0)

    class Reminders:
        def process_due(self):
            reminders_processed.set()

    class WordPress:
        def flush(self):
            wordpress_flushed.set()

    class Scheduler:
        def monotonic(self):
            return 0.0

        def reminder_delay(self, reminders, *, max_delay):
            return max_delay

        def wait(self, seconds, stop_event):
            assert sync_started.wait(0.5)
            assert reminders_processed.wait(0.5)
            assert wordpress_flushed.wait(0.5)
            stop_event.set()
            return True

    service = AssistantService(
        BlockingSync(),
        Reminders(),
        WordPress(),
        FakeIPCServer(),
        FakeDispatcher(),
        Scheduler(),
        max_idle=0.1,
    )
    try:
        service._maintenance_loop()
        deadline = monotonic() + 0.5
        status = service.status()
        while (
            (
                "wordpress.flush" not in status["last_success"]
                or "reminders.process_due" not in status["last_success"]
            )
            and monotonic() < deadline
        ):
            sleep(0.01)
            status = service.status()
        assert "wordpress.flush" in status["last_success"]
        assert "reminders.process_due" in status["last_success"]
    finally:
        release_sync.set()


def test_overdue_reminder_retry_has_low_resource_floor():
    waits = []

    class ImmediateScheduler:
        def __init__(self):
            self.calls = 0

        def monotonic(self):
            return 0.0

        def reminder_delay(self, reminders, *, max_delay):
            return 0.0

        def wait(self, seconds, stop_event):
            waits.append(seconds)
            stop_event.set()
            return True

    service = AssistantService(
        FakeSync(),
        FakeReminders(),
        FakeWordPress(),
        FakeIPCServer(),
        FakeDispatcher(),
        ImmediateScheduler(),
        max_idle=5.0,
    )
    service._maintenance_loop()
    assert waits
    assert waits[0] >= 1.0


def test_slow_next_due_never_blocks_scheduler_thread():
    from threading import Event

    next_due_entered = Event()
    release_next_due = Event()
    waits = []

    class SlowReminders:
        def process_due(self):
            return None

        def next_due(self):
            next_due_entered.set()
            release_next_due.wait(2.0)
            return None

    class Scheduler:
        def monotonic(self):
            return 0.0

        def reminder_delay(self, reminders, *, max_delay):
            reminders.next_due()
            return max_delay

        def wait(self, seconds, stop_event):
            waits.append(seconds)
            assert next_due_entered.wait(0.5)
            stop_event.set()
            return True

    service = AssistantService(
        FakeSync(),
        SlowReminders(),
        FakeWordPress(),
        FakeIPCServer(),
        FakeDispatcher(),
        Scheduler(),
        max_idle=0.2,
    )
    try:
        service._maintenance_loop()
        assert waits and waits[0] > 0
    finally:
        release_next_due.set()
