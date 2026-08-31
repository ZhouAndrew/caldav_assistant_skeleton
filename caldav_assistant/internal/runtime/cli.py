"""CLI-only background lifecycle actions.

This module deliberately stays inside ``internal``.  It composes RuntimeClient and
AutostartManager without exposing IPC or platform service mechanisms to Public API.
"""
from __future__ import annotations

from typing import Any, Callable

from ...api.v1.errors import UnavailableError, ValidationError
from .autostart import AutostartManager
from .process_lifecycle import wait_for_process_exit


class BackgroundActions:
    def __init__(
        self,
        runtime: Any,
        autostart: AutostartManager | Any | None = None,
        ui: Any = None,
        process_waiter: Callable[..., bool] = wait_for_process_exit,
    ) -> None:
        if runtime is None:
            raise TypeError("runtime is required")
        self.runtime = runtime
        self.autostart = autostart or AutostartManager()
        self.ui = ui
        self._process_waiter = process_waiter

    @staticmethod
    def _t(key: str, default: str, **values: Any) -> str:
        # This is a recovery/operations path that must work while the service is
        # stopped.  Production LocaleService reads its selected locale through
        # RemoteSettingsAPI, so consulting it here would itself auto-start IPC.
        # Keep these few lifecycle strings locally formatted instead.
        try:
            return default.format(**values)
        except Exception:
            return default

    def _render(self, status: dict[str, Any] | None = None) -> str:
        status = status or self.runtime.status()
        running = status.get("status") == "running"
        enabled = bool(self.autostart.is_enabled())
        lines = [
            self._t(
                "runtime.background_service",
                "Background service: {state}",
                state="Running" if running else "Stopped",
            ),
            self._t(
                "runtime.background_reminders",
                "Background reminders: {state}",
                state="On" if enabled else "Off",
            ),
        ]
        if running:
            maintenance = status.get("maintenance_alive")
            if maintenance is not None:
                lines.append(
                    self._t(
                        "runtime.maintenance",
                        "Maintenance: {state}",
                        state="Running" if maintenance else "Stopped",
                    )
                )
            if status.get("pid") is not None:
                lines.append(f"PID: {status['pid']}")
        return "\n".join(lines)

    @staticmethod
    def usage() -> str:
        return (
            "background status\n"
            "background start\n"
            "background stop\n"
            "background restart\n"
            "background enable\n"
            "background disable"
        )

    @staticmethod
    def _running_pid(status: dict[str, Any] | None) -> int | None:
        if not isinstance(status, dict) or status.get("status") != "running":
            return None
        try:
            pid = int(status.get("pid"))
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    def _stop_and_wait(self, *, timeout: float = 5.0) -> bool:
        """Stop Runtime and include process teardown in the CLI success boundary.

        A separate one-shot command often attaches to a service launched by an older
        foreground process.  In that case RuntimeClient does not own the Popen handle,
        so endpoint disappearance alone cannot prove the Windows process has released
        SQLite and other file handles.  Capture the authoritative service PID before
        shutdown and wait a bounded time for that process to disappear.
        """
        before = self.runtime.status()
        pid = self._running_pid(before)
        changed = bool(self.runtime.stop())
        if pid is not None and not self._process_waiter(pid, timeout=timeout):
            raise UnavailableError(
                "Background service endpoint stopped but process did not exit in time"
            )
        return changed

    def command(self, *parts: Any) -> str:
        if not all(isinstance(part, str) for part in parts):
            raise ValidationError("background arguments must be text")
        action = str(parts[0]).strip().casefold() if parts else "status"
        if len(parts) > 1:
            raise ValidationError("background accepts one action")

        if action in {"status", "show"}:
            return self._render()
        if action == "start":
            return self._render(self.runtime.ensure_running())
        if action == "stop":
            self._stop_and_wait()
            return self._render()
        if action == "restart":
            self._stop_and_wait()
            return self._render(self.runtime.ensure_running())
        if action in {"enable", "on"}:
            self.autostart.enable()
            return self._render(self.runtime.ensure_running())
        if action in {"disable", "off"}:
            self.autostart.disable(stop=True)
            # A manually launched instance is not necessarily owned by systemd/
            # launchd/schtasks, so also request graceful IPC shutdown and do not
            # report stopped until that actual process has released its resources.
            self._stop_and_wait()
            return self._render()
        if action in {"help", "?"}:
            return self.usage()
        raise ValidationError(f"Unknown background action: {parts[0]}")



def register_background_cli_command(
    commands: Any,
    runtime: Any,
    *,
    autostart: Any = None,
    ui: Any = None,
) -> BackgroundActions:
    actions = BackgroundActions(runtime, autostart=autostart, ui=ui)
    registry = commands.registry
    contains = getattr(registry, "contains", None)
    exists = contains("background") if callable(contains) else ("background" in registry)
    if not exists:
        register = getattr(commands, "register_builtin", None)
        if callable(register):
            register(
                "background",
                actions.command,
                description="Manage the background Assistant service and reminders.",
            )
        else:
            registry.register(
                "background",
                actions.command,
                protected=True,
                description="Manage the background Assistant service and reminders.",
            )
    return actions


__all__ = ["BackgroundActions", "register_background_cli_command"]
