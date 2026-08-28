"""Synchronous Runtime client used by CLI/Object/Easy APIs.

Lifecycle operations are internal conveniences around the same Local IPC transport;
no Task/Event/Agenda business logic is duplicated here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from queue import Empty, Queue
from threading import RLock, Thread
from time import monotonic, sleep
from typing import Any, Callable

from ...api.v1 import errors as public_errors
from .ipc import (
    IPCRemoteError,
    IPCTimeoutError,
    IPCUnavailableError,
    validate_method,
    validate_payload,
)


class RuntimeClient:
    def __init__(
        self,
        ipc: Any,
        launcher: Callable[[], Any] | None = None,
        *,
        request_timeout: float = 10.0,
        startup_timeout: float = 5.0,
        poll_interval: float = 0.10,
    ) -> None:
        self.ipc = ipc
        self.launcher = launcher
        self.request_timeout = float(request_timeout)
        self.startup_timeout = float(startup_timeout)
        self.poll_interval = float(poll_interval)
        if self.request_timeout <= 0 or self.startup_timeout <= 0 or self.poll_interval <= 0:
            raise ValueError("Runtime timeouts must be positive")
        self._launch_lock = RLock()
        self._domain_binders: dict[str, Any] = {}
        # When this client actually launches the service, keep the process handle
        # so lifecycle calls can distinguish "IPC endpoint disappeared" from
        # "the background process has fully exited".  Clients attaching to an
        # already-running/autostarted service simply leave this as None.
        self._launched_process: Any = None

    def bind_domain(self, kind: str, service: Any) -> None:
        if kind not in {"task", "event"}:
            raise ValueError(f"Unsupported domain binder: {kind}")
        self._domain_binders[kind] = service

    def _transport_callable(self) -> Callable[..., Any]:
        call = getattr(self.ipc, "call", None)
        if callable(call):
            return call
        request = getattr(self.ipc, "request", None)
        if callable(request):
            return request
        if callable(self.ipc):
            return self.ipc
        raise RuntimeError("IPC adapter has no call/request method")

    def _bounded_transport(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        limit = self.request_timeout if timeout is None else float(timeout)
        if limit <= 0:
            raise ValueError("Runtime transport timeout must be positive")

        result: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def worker() -> None:
            try:
                result.put((True, self._transport_callable()(method, payload)))
            except BaseException as exc:
                result.put((False, exc))

        Thread(
            target=worker,
            name="caldav-assistant-runtime-call",
            daemon=True,
        ).start()
        try:
            ok, value = result.get(timeout=limit)
        except Empty as exc:
            raise IPCTimeoutError(f"Runtime request timed out: {method}") from exc
        if ok:
            return value
        raise value

    def _map_remote_error(self, exc: IPCRemoteError) -> Exception:
        cls = getattr(public_errors, exc.error_type, None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            return cls(exc.message)
        return RuntimeError(f"{exc.error_type}: {exc.message}")

    @staticmethod
    def _unavailable(message: str) -> Exception:
        cls = getattr(public_errors, "UnavailableError", RuntimeError)
        return cls(message)

    def _execute(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        try:
            result = self._bounded_transport(method, payload, timeout=timeout)
        except IPCRemoteError as exc:
            raise self._map_remote_error(exc) from exc
        return self._bind_result(result)

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - monotonic())

    def _probe_timeout(self, deadline: float, *, ceiling: float = 0.25) -> float:
        remaining = self._remaining(deadline)
        if remaining <= 0:
            return 0.0
        return min(ceiling, self.request_timeout, remaining)

    def _remember_launched_process(self, process: Any) -> None:
        if callable(getattr(process, "poll", None)):
            self._launched_process = process

    def _wait_for_launched_process_exit(self, deadline: float) -> bool:
        process = self._launched_process
        poll = getattr(process, "poll", None)
        if not callable(poll):
            return True

        while True:
            returncode = poll()
            if returncode is not None:
                self._launched_process = None
                return True
            remaining = self._remaining(deadline)
            if remaining <= 0:
                return False
            sleep(min(self.poll_interval, remaining))

    def _wait_until_ready(self, deadline: float, process: Any = None) -> bool:
        while self._remaining(deadline) > 0:
            poll = getattr(process, "poll", None)
            if callable(poll):
                returncode = poll()
                if returncode is not None:
                    return False

            probe_timeout = self._probe_timeout(deadline, ceiling=0.5)
            if probe_timeout <= 0:
                break
            try:
                result = self._bounded_transport(
                    "runtime.ping",
                    {},
                    timeout=probe_timeout,
                )
            except (
                IPCUnavailableError,
                IPCTimeoutError,
                OSError,
                EOFError,
                ConnectionError,
            ):
                sleep(min(self.poll_interval, self._remaining(deadline)))
                continue
            except IPCRemoteError:
                # A structured remote response proves that the endpoint is alive.
                return True
            if isinstance(result, dict) and result.get("status") == "ok":
                return True
            sleep(min(self.poll_interval, self._remaining(deadline)))
        return False

    def _launch_and_wait(self, *, deadline: float | None = None) -> None:
        if self.launcher is None:
            raise self._unavailable("Background service is not running")
        deadline = deadline if deadline is not None else monotonic() + self.startup_timeout

        with self._launch_lock:
            probe_timeout = self._probe_timeout(deadline)
            if probe_timeout > 0 and self.ping(timeout=probe_timeout):
                return
            if self._remaining(deadline) <= 0:
                raise self._unavailable("Background service startup timed out")

            try:
                process = self.launcher()
                self._remember_launched_process(process)
            except Exception as exc:
                raise self._unavailable(
                    f"Could not start background service: {exc}"
                ) from exc

            if not self._wait_until_ready(deadline, process):
                poll = getattr(process, "poll", None)
                returncode = poll() if callable(poll) else None
                if returncode is not None:
                    if process is self._launched_process:
                        self._launched_process = None
                    raise self._unavailable(
                        f"Background service exited during startup (code {returncode})"
                    )
                raise self._unavailable(
                    "Background service did not become ready in time"
                )

    def _bind_result(self, value: Any) -> Any:
        name = value.__class__.__name__ if value is not None else ""
        if name == "Task" and "task" in self._domain_binders:
            try:
                value._service = self._domain_binders["task"]
            except Exception:
                pass
            return value
        if name == "Event" and "event" in self._domain_binders:
            try:
                value._service = self._domain_binders["event"]
            except Exception:
                pass
            return value
        if name == "ActionResult" and hasattr(value, "affected"):
            try:
                value.affected = self._bind_result(value.affected)
            except Exception:
                pass
            return value
        if isinstance(value, list):
            return [self._bind_result(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._bind_result(item) for item in value)
        if isinstance(value, Mapping):
            return {key: self._bind_result(item) for key, item in value.items()}
        if is_dataclass(value) and not isinstance(value, type):
            # Rebind nested public containers such as
            # Agenda -> AgendaItem -> Task/Event after transport detachment.
            for field in fields(value):
                if field.name == "_service":
                    continue
                try:
                    setattr(
                        value,
                        field.name,
                        self._bind_result(getattr(value, field.name)),
                    )
                except Exception:
                    pass
            return value
        return value

    def ping(self, *, timeout: float | None = None) -> bool:
        """Probe the service without auto-starting it."""
        limit = (
            min(0.25, self.startup_timeout, self.request_timeout)
            if timeout is None
            else float(timeout)
        )
        if limit <= 0:
            return False
        try:
            result = self._bounded_transport("runtime.ping", {}, timeout=limit)
        except (
            IPCUnavailableError,
            IPCTimeoutError,
            OSError,
            EOFError,
            ConnectionError,
        ):
            return False
        except IPCRemoteError:
            return True
        return isinstance(result, dict) and result.get("status") == "ok"

    @staticmethod
    def _stopped_status() -> dict[str, Any]:
        return {
            "status": "stopped",
            "pid": None,
            "started_at": None,
            "maintenance_alive": False,
            "last_success": {},
            "last_errors": {},
        }

    def status(self, *, start: bool = False) -> dict[str, Any]:
        """Return service status; probing alone never starts a stopped service."""
        if start:
            return self.ensure_running()
        if not self.ping():
            return self._stopped_status()
        try:
            value = self._execute(
                "runtime.status",
                {},
                timeout=min(self.request_timeout, 1.0),
            )
        except (
            IPCUnavailableError,
            IPCTimeoutError,
            OSError,
            EOFError,
            ConnectionError,
        ):
            return self._stopped_status()
        if not isinstance(value, dict):
            raise RuntimeError("Invalid runtime.status response")
        return value

    def ensure_running(self) -> dict[str, Any]:
        """Ensure the singleton background service is ready, then return its status."""
        deadline = monotonic() + self.startup_timeout
        probe_timeout = self._probe_timeout(deadline)
        if probe_timeout <= 0 or not self.ping(timeout=probe_timeout):
            self._launch_and_wait(deadline=deadline)

        remaining = self._remaining(deadline)
        if remaining <= 0:
            # A successful ping at the deadline is still sufficient readiness;
            # callers can request detailed status separately.
            return {
                "status": "running",
                "pid": None,
                "started_at": None,
            }
        try:
            value = self._execute(
                "runtime.status",
                {},
                timeout=min(self.request_timeout, remaining),
            )
        except (IPCUnavailableError, IPCTimeoutError) as exc:
            raise self._unavailable(
                "Background service became unavailable during startup"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError("Invalid runtime.status response")
        return value

    def stop(self, *, timeout: float = 5.0) -> bool:
        """Gracefully stop a running service; never auto-start an absent one.

        If this RuntimeClient launched the process itself, success means both the
        IPC endpoint and that known child process have exited.  This closes a
        subtle lifecycle gap where the socket was already removed while process
        teardown was still in progress.
        """
        limit = float(timeout)
        if limit <= 0:
            raise ValueError("stop timeout must be positive")
        deadline = monotonic() + limit

        probe_timeout = self._probe_timeout(deadline)
        if probe_timeout <= 0 or not self.ping(timeout=probe_timeout):
            if self._wait_for_launched_process_exit(deadline):
                return False
            raise self._unavailable(
                "Background service endpoint stopped but process did not exit in time"
            )

        remaining = self._remaining(deadline)
        if remaining <= 0:
            raise self._unavailable("Background service shutdown timed out")
        try:
            self._execute(
                "runtime.shutdown",
                {},
                timeout=min(self.request_timeout, 1.0, remaining),
            )
        except (IPCUnavailableError, EOFError, ConnectionError):
            # Closing immediately after the acknowledgement still means stop.
            pass
        except IPCTimeoutError as exc:
            raise self._unavailable(
                "Background service shutdown request timed out"
            ) from exc

        while self._remaining(deadline) > 0:
            probe_timeout = self._probe_timeout(deadline)
            if probe_timeout <= 0 or not self.ping(timeout=probe_timeout):
                if self._wait_for_launched_process_exit(deadline):
                    return True
                break
            sleep(min(self.poll_interval, self._remaining(deadline)))
        raise self._unavailable("Background service did not stop in time")

    def restart(self, *, timeout: float = 5.0) -> dict[str, Any]:
        self.stop(timeout=timeout)
        return self.ensure_running()

    def call(self, method: str, **payload: Any) -> Any:
        clean = validate_method(method)
        body = validate_payload(payload)
        try:
            return self._execute(clean, body)
        except IPCTimeoutError as exc:
            raise self._unavailable(f"Runtime request timed out: {clean}") from exc
        except IPCUnavailableError:
            deadline = monotonic() + self.startup_timeout
            self._launch_and_wait(deadline=deadline)
            try:
                return self._execute(clean, body)
            except IPCTimeoutError as exc:
                raise self._unavailable(
                    f"Runtime request timed out after startup: {clean}"
                ) from exc
            except IPCUnavailableError as exc:
                raise self._unavailable(
                    "Background service became unavailable after startup"
                ) from exc

    def request(
        self,
        method: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        return self.call(method, **validate_payload(payload))


__all__ = ["RuntimeClient"]
