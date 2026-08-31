"""Installed CLI entrypoint that prevents new clients from using stale daemon code."""
from __future__ import annotations

import sys
from typing import Any, Sequence

from ...api.v1.errors import UnavailableError
from ..runtime.build_identity import RUNTIME_BUILD_IDENTITY
# Keep this binding name for compatibility with existing entrypoint tests/tools while
# routing the installed interactive client through the zero-learning conversation UI
# with factual live Core progress.
from . import conversation_live as monitor_app
from .latency_guard import install as install_latency_guards


def _show(app: Any, text: str) -> None:
    ui = getattr(getattr(app, "ctx", None), "ui", None)
    show = getattr(ui, "show", None)
    if callable(show):
        show(text)
        return
    io = getattr(app, "io", None)
    write = getattr(io, "write", None)
    if callable(write):
        write(text)


def _is_background_admin(argv: Sequence[str]) -> bool:
    return bool(argv and str(argv[0]).strip().casefold() == "background")


def ensure_current_background(app: Any) -> bool:
    """Restart a running daemon when it loaded a different source generation.

    A stopped daemon is left stopped; ordinary RuntimeClient behavior may start it
    later when a command actually needs IPC. A running pre-handshake daemon has no
    ``runtime_identity`` field and is intentionally treated as stale.
    """
    runtime = getattr(app, "runtime", None)
    if runtime is None:
        return False

    status = runtime.status()
    if not isinstance(status, dict) or status.get("status") != "running":
        return False

    loaded = status.get("runtime_identity")
    if loaded == RUNTIME_BUILD_IDENTITY:
        return False

    old_pid = status.get("pid")
    try:
        restarted = runtime.restart(timeout=5.0)
    except Exception as exc:
        raise UnavailableError(
            "Background service is running older code and could not be restarted safely: "
            f"{exc}"
        ) from exc

    if not isinstance(restarted, dict):
        restarted = runtime.status()
    fresh_identity = restarted.get("runtime_identity") if isinstance(restarted, dict) else None
    if fresh_identity != RUNTIME_BUILD_IDENTITY:
        fresh = runtime.status()
        fresh_identity = fresh.get("runtime_identity") if isinstance(fresh, dict) else None
        if fresh_identity != RUNTIME_BUILD_IDENTITY:
            raise UnavailableError(
                "Background service restart completed, but the running daemon still "
                "does not match this CLI build. Refusing to send Task/Event operations "
                "to stale code."
            )

    new_pid = restarted.get("pid") if isinstance(restarted, dict) else None
    detail = ""
    if old_pid or new_pid:
        detail = f" (PID {old_pid or '?'} -> {new_pid or '?'})"
    _show(
        app,
        "Background service code changed; restarted the stale daemon automatically"
        f"{detail}.",
    )
    return True


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if app is None:
        from ..bootstrap import build_cli_application

        app = build_cli_application()

    # Background administration commands must keep their existing semantics:
    # `background status` is read-only, `stop` must be able to stop a legacy daemon,
    # and explicit restart already performs the lifecycle transition itself.
    if not _is_background_admin(argv):
        ensure_current_background(app)
        install_latency_guards(monitor_app)
    return monitor_app.run_cli(argv, app=app)


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ensure_current_background", "run_cli", "main"]
