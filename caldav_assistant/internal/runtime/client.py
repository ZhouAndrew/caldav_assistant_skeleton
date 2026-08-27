"""Synchronous Runtime client used by CLI/Object/Easy APIs."""
from __future__ import annotations

from collections.abc import Mapping
from queue import Empty, Queue
from threading import RLock, Thread
from time import monotonic, sleep
from typing import Any, Callable

from ...api.v1 import errors as public_errors
from .ipc import IPCRemoteError, IPCTimeoutError, IPCUnavailableError, validate_method, validate_payload

class RuntimeClient:
    def __init__(self, ipc: Any, launcher: Callable[[], Any] | None = None, *, request_timeout: float = 10.0, startup_timeout: float = 5.0, poll_interval: float = 0.10) -> None:
        self.ipc = ipc; self.launcher = launcher
        self.request_timeout = float(request_timeout); self.startup_timeout = float(startup_timeout); self.poll_interval = float(poll_interval)
        if self.request_timeout <= 0 or self.startup_timeout <= 0 or self.poll_interval <= 0:
            raise ValueError("Runtime timeouts must be positive")
        self._launch_lock = RLock(); self._domain_binders: dict[str, Any] = {}

    def bind_domain(self, kind: str, service: Any) -> None:
        if kind not in {"task", "event"}: raise ValueError(f"Unsupported domain binder: {kind}")
        self._domain_binders[kind] = service

    def _transport_callable(self) -> Callable[..., Any]:
        call = getattr(self.ipc, "call", None)
        if callable(call): return call
        request = getattr(self.ipc, "request", None)
        if callable(request): return request
        if callable(self.ipc): return self.ipc
        raise RuntimeError("IPC adapter has no call/request method")

    def _bounded_transport(self, method: str, payload: dict[str, Any]) -> Any:
        queue: Queue[tuple[bool, Any]] = Queue(maxsize=1)
        def worker() -> None:
            try: queue.put((True, self._transport_callable()(method, payload)))
            except BaseException as exc: queue.put((False, exc))
        Thread(target=worker, name="caldav-assistant-runtime-call", daemon=True).start()
        try: ok, value = queue.get(timeout=self.request_timeout)
        except Empty as exc: raise IPCTimeoutError(f"Runtime request timed out: {method}") from exc
        if ok: return value
        raise value

    def _map_remote_error(self, exc: IPCRemoteError) -> Exception:
        cls = getattr(public_errors, exc.error_type, None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            return cls(exc.message)
        return exc

    def _launch_and_wait(self) -> None:
        if self.launcher is None: raise IPCUnavailableError("Background service is not running")
        with self._launch_lock:
            try:
                self._bounded_transport("runtime.ping", {})
                return
            except Exception:
                pass
            self.launcher()
            deadline = monotonic() + self.startup_timeout
            last: Exception | None = None
            while monotonic() < deadline:
                try:
                    self._bounded_transport("runtime.ping", {})
                    return
                except Exception as exc:
                    last = exc; sleep(self.poll_interval)
            raise IPCUnavailableError("Background service did not become ready") from last

    def _bind_result(self, value: Any) -> Any:
        name = value.__class__.__name__ if value is not None else ""
        if name == "Task" and "task" in self._domain_binders:
            try: value._service = self._domain_binders["task"]
            except Exception: pass
            return value
        if name == "Event" and "event" in self._domain_binders:
            try: value._service = self._domain_binders["event"]
            except Exception: pass
            return value
        if name == "ActionResult" and hasattr(value, "affected"):
            try: value.affected = self._bind_result(value.affected)
            except Exception: pass
            return value
        if isinstance(value, list): return [self._bind_result(v) for v in value]
        if isinstance(value, tuple): return tuple(self._bind_result(v) for v in value)
        if isinstance(value, Mapping): return {k: self._bind_result(v) for k, v in value.items()}
        return value

    def call(self, method: str, **payload: Any) -> Any:
        clean = validate_method(method); body = validate_payload(payload)
        try:
            result = self._bounded_transport(clean, body)
        except IPCUnavailableError:
            self._launch_and_wait(); result = self._bounded_transport(clean, body)
        except IPCRemoteError as exc:
            raise self._map_remote_error(exc) from exc
        try: return self._bind_result(result)
        except IPCRemoteError as exc: raise self._map_remote_error(exc) from exc

    def request(self, method: str, payload: Mapping[str, Any] | None = None) -> Any:
        return self.call(method, **validate_payload(payload))

__all__ = ["RuntimeClient"]
