"""Real-use latency guards for the installed terminal client.

This module contains presentation/runtime composition only. It does not cache Task or
Event truth and does not change mutation timeouts. Its two responsibilities are:

* bound the non-mutating startup snapshot so a sick CalDAV read cannot hold the
  terminal for the RuntimeClient's general 30-second mutation-safe timeout; and
* keep modal shell menus on the main thread, where terminal input and Ctrl-C belong.

Normal Task/Event operations continue through the same CommandService/Core/Local IPC
path. CalDAV remains authoritative.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any

from ...api.v1.errors import UnavailableError
from ..runtime.ipc import (
    IPCTimeoutError,
    IPCUnavailableError,
    validate_method,
    validate_payload,
)


STARTUP_READ_TIMEOUT_SECONDS = 8.0
_MAIN_THREAD_SHELLS = frozenset({"history", "menu", "settings"})


def _bounded_read_call(app: Any, method: str, **payload: Any) -> Any:
    """Run one read-only startup IPC request with a presentation latency budget."""
    runtime = getattr(app, "runtime", None)
    execute = getattr(runtime, "_execute", None)
    if not callable(execute):
        # Replacement Runtime clients retain their documented call contract. They do
        # not get the private optimization, but compatibility remains intact.
        call = getattr(runtime, "call", None)
        if not callable(call):
            raise UnavailableError("This client has no background Runtime connection")
        return call(method, **payload)

    clean = validate_method(method)
    body = validate_payload(payload)

    ping = getattr(runtime, "ping", None)
    ensure = getattr(runtime, "ensure_running", None)
    try:
        if callable(ping) and not ping(timeout=0.25):
            if not callable(ensure):
                raise UnavailableError("Background service is not running")
            ensure()
        return execute(clean, body, timeout=STARTUP_READ_TIMEOUT_SECONDS)
    except IPCTimeoutError as exc:
        raise UnavailableError(
            f"Startup live read exceeded {STARTUP_READ_TIMEOUT_SECONDS:g}s: {clean}"
        ) from exc
    except IPCUnavailableError as exc:
        raise UnavailableError(
            f"Background service became unavailable during startup read: {clean}"
        ) from exc


def _read_snapshot(module: Any, app: Any) -> Any:
    """Read current work, agenda and recommendation without duplicate Session I/O."""
    conversation = module.conversation
    hours = conversation._window_hours(app)
    now = datetime.now().astimezone()
    end = now + timedelta(hours=hours)
    days = max(1, int(math.ceil(hours / 24.0)) + 1)

    runtime = getattr(app, "runtime", None)
    runtime_call = getattr(runtime, "call", None)
    if callable(runtime_call):
        bundle = _bounded_read_call(
            app,
            "agenda.startup_snapshot",
            days=days,
            kind="task",
        )
        if not isinstance(bundle, dict):
            raise RuntimeError("Invalid startup agenda response")
        agenda = bundle.get("agenda")
        recommendation = bundle.get("recommendation")
        current = bundle.get("current_task")
    else:
        # Deliberately small test contexts may have no Runtime connection.
        session = getattr(app.ctx, "session", None)
        current_getter = getattr(session, "current_task", None)
        current = current_getter() if callable(current_getter) else None
        agenda = app.ctx.agenda.range(days=days)
        try:
            recommendation = app.ctx.agenda.next(kind="task")
        except TypeError:
            recommendation = app.ctx.agenda.next()

    values = tuple(
        item
        for item in getattr(agenda, "items", ())
        if conversation._item_in_window(item, now, end)
    )
    recommendation = getattr(recommendation, "value", recommendation)
    if recommendation is not None:
        if bool(getattr(recommendation, "completed", False)) or str(
            getattr(recommendation, "status", "")
        ) == "CANCELLED":
            recommendation = None

    return conversation.StartupSnapshot(
        current_task=current,
        upcoming=values,
        recommended=recommendation,
        window_hours=hours,
    )


def _canonical_shell(app: Any, parsed: Any) -> str | None:
    """Identify commands whose no-argument body is itself a modal terminal shell."""
    if tuple(getattr(parsed, "args", ()) or ()):
        return None
    try:
        entry = app.commands.resolve(parsed.name)
    except Exception:
        return None
    name = str(getattr(entry, "name", "") or "").strip().casefold()
    return name if name in _MAIN_THREAD_SHELLS else None


def _execute_shell_on_main(module: Any, app: Any, parsed: Any, *, paginate: bool) -> tuple[int, bool]:
    """Execute only the modal shell wrapper on the terminal-owning main thread."""
    conversation = module.conversation
    original = parsed
    effective, period_seconds = module.legacy._split_lifecycle_duration(parsed)
    # These are shell/menu commands, never lifecycle-duration commands. Keep this
    # invariant explicit so a future alias cannot silently lose work-period behavior.
    if period_seconds is not None:
        return module._execute_user_unbounded(app, parsed, paginate=paginate)

    conversation._show(app, "")
    conversation._show(app, f"Working: {original.raw}")
    conversation._show(
        app,
        "Choose an item; waiting for your input is not operation latency.",
    )
    code, should_exit, result = module._run_command_without_render(app, effective)
    if result is not None:
        module.base._render_result(app, result, paginate=paginate)

    # Deliberately do not print elapsed seconds here: this interval includes the
    # human's menu think-time and calling it operation latency would recreate the
    # original misleading behavior in a different form.
    if code == 0:
        conversation._show(app, "✓ Menu/selection finished.")
    else:
        conversation._show(app, "✗ Menu/selection did not fully succeed.")
    return code, should_exit


def install(module: Any) -> None:
    """Install guards idempotently before conversation_live installs its bricks."""
    if bool(getattr(module, "_latency_guards_installed", False)):
        return

    original_execute = module._execute_user
    module._execute_user_unbounded = original_execute

    def guarded_read_snapshot(app: Any) -> Any:
        return _read_snapshot(module, app)

    def guarded_execute_user(app: Any, parsed: Any, *, paginate: bool = True):
        if _canonical_shell(app, parsed) is not None:
            return _execute_shell_on_main(module, app, parsed, paginate=paginate)
        return original_execute(app, parsed, paginate=paginate)

    module._read_snapshot = guarded_read_snapshot
    module._execute_user = guarded_execute_user
    module._latency_guards_installed = True


__all__ = ["STARTUP_READ_TIMEOUT_SECONDS", "install"]
