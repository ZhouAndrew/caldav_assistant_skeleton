"""Production observable daemon with a frozen per-process source identity."""
from __future__ import annotations

from typing import Any
import os
import signal

from .build_identity import RUNTIME_BUILD_IDENTITY
from .ipc import IPCAlreadyRunningError
from .observable_service import ObservableAssistantService


class VersionedObservableAssistantService(ObservableAssistantService):
    """Observable service that tells clients exactly which code generation is loaded."""

    def _handle_request(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        if method == "runtime.ping":
            return {
                "status": "ok",
                "pid": os.getpid(),
                "runtime_identity": RUNTIME_BUILD_IDENTITY,
            }
        return super()._handle_request(method, payload)

    def status(self) -> dict[str, Any]:
        value = super().status()
        value["runtime_identity"] = RUNTIME_BUILD_IDENTITY
        return value


def build_versioned_observable_service() -> VersionedObservableAssistantService:
    from ..bootstrap import build_service_application

    application = build_service_application()
    base = application.background
    return VersionedObservableAssistantService(
        base.sync,
        base.reminders,
        base.wordpress,
        base.ipc_server,
        base.dispatcher,
        base.scheduler,
        sync_interval=base.sync_interval,
        wordpress_interval=base.wordpress_interval,
        max_idle=base.max_idle,
    )


def main() -> int:
    service = build_versioned_observable_service()

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


__all__ = [
    "VersionedObservableAssistantService",
    "build_versioned_observable_service",
    "main",
]
