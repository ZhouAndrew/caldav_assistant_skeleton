"""Authoritative lightweight Assistant background service.

Orchestration only: Local IPC, low-frequency maintenance, Reminder wakeups.
Task/Event business logic remains in Core Services behind RuntimeDispatcher.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, RLock, Thread, Timer, current_thread
from typing import Any
import os
import signal

from .ipc import IPCAlreadyRunningError
from .scheduler import PlatformWakeScheduler


class AssistantService:
    def __init__(
        self,
        sync: Any,
        reminders: Any,
        wordpress: Any,
        ipc_server: Any,
        dispatcher: Any,
        scheduler: Any | None = None,
        *,
        sync_interval: float = 60.0,
        wordpress_interval: float = 60.0,
        max_idle: float = 30.0,
    ) -> None:
        self.sync = sync
        self.reminders = reminders
        self.wordpress = wordpress
        self.ipc_server = ipc_server
        self.dispatcher = dispatcher
        self.scheduler = scheduler or PlatformWakeScheduler()
        self.sync_interval = float(sync_interval)
        self.wordpress_interval = float(wordpress_interval)
        self.max_idle = float(max_idle)
        if self.sync_interval <= 0 or self.wordpress_interval <= 0 or self.max_idle <= 0:
            raise ValueError("Background service intervals must be positive")

        self._stop_event = Event()
        self._running = Event()
        self._lock = RLock()
        self._started_at: datetime | None = None
        self._last_success: dict[str, str] = {}
        self._last_errors: dict[str, str] = {}
        self._maintenance_thread: Thread | None = None
        self._maintenance_jobs: dict[str, Thread] = {}
        self._next_reminder_wake = 0.0

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def _record_error(self, label: str, exc: BaseException) -> None:
        with self._lock:
            self._last_errors[label] = f"{type(exc).__name__}: {exc}"

    def _clear_error(self, label: str) -> None:
        with self._lock:
            self._last_errors.pop(label, None)

    def _run_one(self, label: str, target: Any, *args: Any, **kwargs: Any) -> None:
        if not callable(target):
            return
        try:
            target(*args, **kwargs)
        except Exception as exc:
            self._record_error(label, exc)
            return
        with self._lock:
            self._last_success[label] = datetime.now(timezone.utc).isoformat()
            self._last_errors.pop(label, None)

    def _start_maintenance_job(
        self,
        label: str,
        target: Any,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """Start one isolated maintenance job without overlapping the same job.

        Network-backed Core operations can take seconds even when they are correctly
        bounded.  Running them serially would let CalDAV discovery starve reminders
        and the WordPress Outbox.  Each label therefore has at most one daemon worker
        while the scheduler remains free to service the other maintenance lanes.
        """
        if not callable(target) or self._stop_event.is_set():
            return False

        with self._lock:
            existing = self._maintenance_jobs.get(label)
            if existing is not None and existing.is_alive():
                return False

            def worker() -> None:
                try:
                    self._run_one(label, target, *args, **kwargs)
                finally:
                    with self._lock:
                        if self._maintenance_jobs.get(label) is current_thread():
                            self._maintenance_jobs.pop(label, None)

            thread = Thread(
                target=worker,
                name=f"caldav-assistant-job-{label}",
                daemon=True,
            )
            self._maintenance_jobs[label] = thread
            thread.start()
            return True

    def _reminder_delay(self) -> float:
        """Compute the next reminder delay inside the isolated reminder lane."""
        try:
            delay = self.scheduler.reminder_delay(
                self.reminders,
                max_delay=self.max_idle,
            )
            delay = max(0.0, min(self.max_idle, float(delay)))
        except Exception as exc:
            self._record_error("reminders.next_due", exc)
            return self.max_idle
        self._clear_error("reminders.next_due")
        return delay

    def _run_reminder_cycle(self) -> None:
        """Process reminders and publish the next monotonic wake deadline.

        ``ReminderService.next_due()`` may read Task/Event facts and therefore can
        involve bounded CalDAV work.  Keep that work out of the scheduler thread: a
        slow reminder source must not turn the orchestration loop into a busy loop or
        block WordPress/sync scheduling.
        """
        self._run_one(
            "reminders.process_due",
            getattr(self.reminders, "process_due", None),
        )
        delay = self._reminder_delay()
        if delay <= 0:
            # An overdue request that could not be delivered must not trigger a
            # full Task/Event reminder evaluation every second.  Five seconds is
            # still prompt for retry while remaining appropriate for old hardware.
            delay = min(self.max_idle, 5.0)
        with self._lock:
            self._next_reminder_wake = self.scheduler.monotonic() + delay

    def run_maintenance_once(self) -> None:
        incremental = getattr(self.sync, "incremental_sync", None) or getattr(
            self.sync, "refresh", None
        )
        self._run_one("sync.incremental", incremental)
        self._run_one(
            "reminders.process_due",
            getattr(self.reminders, "process_due", None),
        )
        self._run_one("wordpress.flush", getattr(self.wordpress, "flush", None))

    def _maintenance_loop(self) -> None:
        next_sync = 0.0
        next_wordpress = 0.0
        while not self._stop_event.is_set():
            try:
                now = self.scheduler.monotonic()
                if now >= next_sync:
                    incremental = getattr(self.sync, "incremental_sync", None) or getattr(
                        self.sync, "refresh", None
                    )
                    self._start_maintenance_job("sync.incremental", incremental)
                    next_sync = now + self.sync_interval

                with self._lock:
                    next_reminder = self._next_reminder_wake
                if now >= next_reminder:
                    started = self._start_maintenance_job(
                        "reminders.cycle",
                        self._run_reminder_cycle,
                    )
                    if started:
                        # Reserve a bounded fallback deadline immediately.  The
                        # worker replaces it with the precise next_due deadline when
                        # its evaluation completes.
                        with self._lock:
                            self._next_reminder_wake = now + self.max_idle

                if now >= next_wordpress:
                    self._start_maintenance_job(
                        "wordpress.flush",
                        getattr(self.wordpress, "flush", None),
                    )
                    next_wordpress = now + self.wordpress_interval

                with self._lock:
                    next_reminder = self._next_reminder_wake
                delay = min(
                    self.max_idle,
                    max(0.0, next_sync - now),
                    max(0.0, next_wordpress - now),
                    max(0.0, next_reminder - now),
                )
                if delay <= 0:
                    # A worker may still be finishing while its reserved deadline
                    # expires.  Never spin the scheduler while waiting for it.
                    delay = min(self.max_idle, 1.0)
                self.scheduler.wait(delay, self._stop_event)
                self._clear_error("runtime.maintenance")
            except Exception as exc:
                # Last-resort orchestration boundary. A platform/scheduler defect
                # is recorded and retried instead of silently killing the thread.
                self._record_error("runtime.maintenance", exc)
                self._stop_event.wait(min(1.0, max(0.05, self.max_idle)))

    def _handle_request(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if method == "runtime.ping":
            return {"status": "ok", "pid": os.getpid()}
        if method == "runtime.status":
            return self.status()
        if method == "runtime.shutdown":
            # Acknowledge first, then close the listener asynchronously so the
            # requesting client receives a structured success response.
            timer = Timer(0.05, self.stop)
            timer.daemon = True
            timer.start()
            return {"status": "stopping", "pid": os.getpid()}
        return self.dispatcher.handle(method, payload or {})

    def status(self) -> dict[str, Any]:
        with self._lock:
            thread = self._maintenance_thread
            return {
                "status": "running" if self.running else "stopped",
                "pid": os.getpid(),
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "maintenance_alive": bool(thread and thread.is_alive()),
                "maintenance_jobs": sorted(
                    label
                    for label, job in self._maintenance_jobs.items()
                    if job.is_alive()
                ),
                "last_success": dict(self._last_success),
                "last_errors": dict(self._last_errors),
            }

    def run_forever(self) -> None:
        if self._running.is_set():
            raise RuntimeError("AssistantService is already running")

        self._stop_event.clear()
        self._started_at = None
        self._maintenance_thread = None
        self._next_reminder_wake = 0.0

        def mark_ready() -> None:
            # The Local IPC singleton is authoritative for process ownership.
            # Start maintenance only after the endpoint has been bound successfully,
            # so a concurrent losing launcher never performs duplicate Core work.
            self._started_at = datetime.now(timezone.utc)
            self._running.set()
            thread = Thread(
                target=self._maintenance_loop,
                name="caldav-assistant-maintenance",
                daemon=True,
            )
            self._maintenance_thread = thread
            thread.start()

        try:
            self.ipc_server.serve_forever(
                self._handle_request,
                self._stop_event,
                on_ready=mark_ready,
            )
        finally:
            self._stop_event.set()
            close = getattr(self.ipc_server, "close", None)
            if callable(close):
                close()
            thread = self._maintenance_thread
            if (
                thread is not None
                and thread is not current_thread()
                and thread.is_alive()
            ):
                thread.join(timeout=2.0)
            self._running.clear()

    start = run_forever

    def stop(self) -> None:
        self._stop_event.set()
        close = getattr(self.ipc_server, "close", None)
        if callable(close):
            close()


def main() -> int:
    from ..bootstrap import build_service_application

    application = build_service_application()
    service = application.background

    def request_stop(signum: int, frame: Any) -> None:
        service.stop()

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):
                pass

    try:
        service.run_forever()
    except IPCAlreadyRunningError:
        return 0
    except KeyboardInterrupt:
        service.stop()
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AssistantService", "main"]
