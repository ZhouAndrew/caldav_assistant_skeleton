"""CLI-only background lifecycle actions.

This module deliberately stays inside ``internal``.  It composes RuntimeClient and
AutostartManager without exposing IPC or platform service mechanisms to Public API.
"""
from __future__ import annotations

from typing import Any

from ...api.v1.errors import ValidationError
from .autostart import AutostartManager


class BackgroundActions:
    def __init__(
        self,
        runtime: Any,
        autostart: AutostartManager | Any | None = None,
        ui: Any = None,
    ) -> None:
        if runtime is None:
            raise TypeError("runtime is required")
        self.runtime = runtime
        self.autostart = autostart or AutostartManager()
        self.ui = ui

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
            self.runtime.stop()
            return self._render()
        if action == "restart":
            return self._render(self.runtime.restart())
        if action in {"enable", "on"}:
            self.autostart.enable()
            return self._render(self.runtime.ensure_running())
        if action in {"disable", "off"}:
            self.autostart.disable(stop=True)
            # A manually launched instance is not necessarily owned by systemd/
            # launchd/schtasks, so also request graceful IPC shutdown.
            self.runtime.stop()
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
