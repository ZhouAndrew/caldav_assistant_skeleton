from __future__ import annotations

from time import sleep
from types import SimpleNamespace
from threading import Event

from caldav_assistant.api import Agenda
from caldav_assistant.internal.cli import latency_guard
from caldav_assistant.internal.runtime.ipc import IPCTimeoutError


def _cached_bundle():
    return {
        "agenda": Agenda(),
        "recommendation": None,
        "current_task": None,
        "tasks": (),
        "stale": True,
    }


def test_slow_live_read_has_cache_recovery_already_in_flight(monkeypatch):
    monkeypatch.setattr(latency_guard, "STARTUP_READ_TIMEOUT_SECONDS", 0.20)
    monkeypatch.setattr(latency_guard, "STARTUP_CACHE_FALLBACK_TIMEOUT_SECONDS", 0.20)
    monkeypatch.setattr(latency_guard, "_CACHE_PREFETCH_LEAD_SECONDS", 0.19)
    monkeypatch.setattr(latency_guard, "_CACHE_FALLBACK_COMPLETION_WAIT_SECONDS", 0.20)

    cache_started = Event()
    allow_cache = Event()

    class Runtime:
        def __init__(self):
            self.calls = []

        def ping(self, *, timeout=None):
            return True

        def _execute(self, method, payload, *, timeout=None):
            self.calls.append((method, timeout))
            if method == "agenda.startup_snapshot":
                assert cache_started.wait(0.5), "cache recovery did not prefetch"
                allow_cache.set()
                raise IPCTimeoutError("slow live read")
            assert method == "agenda.cached_startup_snapshot"
            cache_started.set()
            assert allow_cache.wait(0.5)
            return _cached_bundle()

    runtime = Runtime()
    value = latency_guard._bounded_read_call(
        SimpleNamespace(runtime=runtime),
        "agenda.startup_snapshot",
        days=1,
        kind="task",
    )

    assert value["stale"] is True
    assert [method for method, _ in runtime.calls] == [
        "agenda.startup_snapshot",
        "agenda.cached_startup_snapshot",
    ]


def test_fast_live_read_cancels_delayed_cache_prefetch(monkeypatch):
    monkeypatch.setattr(latency_guard, "STARTUP_READ_TIMEOUT_SECONDS", 0.10)
    monkeypatch.setattr(latency_guard, "_CACHE_PREFETCH_LEAD_SECONDS", 0.05)

    class Runtime:
        def __init__(self):
            self.calls = []

        def ping(self, *, timeout=None):
            return True

        def _execute(self, method, payload, *, timeout=None):
            self.calls.append(method)
            if method == "agenda.startup_snapshot":
                return {**_cached_bundle(), "stale": False}
            raise AssertionError("healthy startup must not read the stale cache")

    runtime = Runtime()
    value = latency_guard._bounded_read_call(
        SimpleNamespace(runtime=runtime),
        "agenda.startup_snapshot",
        days=1,
        kind="task",
    )
    sleep(0.08)

    assert value["stale"] is False
    assert runtime.calls == ["agenda.startup_snapshot"]
