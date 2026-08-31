"""Real-use latency guards for the installed terminal client.

This module contains presentation/runtime composition only. It does not cache Task or
Event truth and does not change mutation timeouts. Its responsibilities are:

* bound the non-mutating startup snapshot so a sick CalDAV read cannot hold the
  terminal for the RuntimeClient's general 30-second mutation-safe timeout;
* keep modal shell menus on the main thread, where terminal input and Ctrl-C belong;
  and
* make one guided-menu visit use one live snapshot, while a failed read degrades to a
  clearly marked unavailable snapshot instead of terminating the whole CLI.

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
_UPCOMING_REFRESH_LABEL = "Refreshing Upcoming…"
_HOME_REFRESH_LABEL = "Refreshing current work, Tasks and Events…"


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


def _unavailable_snapshot(conversation: Any, app: Any, exc: Exception) -> Any:
    """Create presentation-only degraded state after a live read failed."""
    return conversation.StartupSnapshot(
        window_hours=conversation._window_hours(app),
        warning=(
            "Live Task/Event data is temporarily unavailable; no Task/Event state "
            f"was changed. {type(exc).__name__}: {exc}"
        ),
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
    outcome = module.base.execute_command(app, effective)
    if outcome.result is not None:
        module.base._render_result(app, outcome.result, paginate=paginate)

    # Deliberately do not print elapsed seconds here: this interval includes the
    # human's menu think-time and calling it operation latency would recreate the
    # original misleading behavior in a different form.
    if outcome.exit_code == 0:
        conversation._show(app, "✓ Menu/selection finished.")
    else:
        conversation._show(app, "✗ Menu/selection did not fully succeed.")
    return outcome.exit_code, outcome.should_exit


def install(module: Any) -> None:
    """Install guards idempotently before conversation_live installs its bricks."""
    if bool(getattr(module, "_latency_guards_installed", False)):
        return

    conversation = module.conversation
    original_execute = module._execute_user
    original_home_menu = conversation._home_menu
    original_visible_call = conversation._visible_call
    module._execute_user_unbounded = original_execute

    # A menu is a view over one coherent point-in-time snapshot. The old path read a
    # snapshot to decide which menu labels to show and then performed the same live
    # CalDAV read again when the human selected Upcoming. Besides doubling latency,
    # the second read could hit the 8s budget and tear down the entire REPL. Keep the
    # one snapshot only for the lifetime of this menu call; it is not a Task cache or
    # a source of truth and is discarded as soon as the user leaves the menu.
    menu_state: dict[str, Any] = {"snapshot": None}

    def guarded_read_snapshot(app: Any) -> Any:
        snapshot = menu_state["snapshot"]
        if snapshot is not None and getattr(snapshot, "warning", None) is None:
            return snapshot
        return _read_snapshot(module, app)

    def guarded_visible_call(app: Any, label: str, fn: Any, *args: Any, **kwargs: Any):
        snapshot = menu_state["snapshot"]
        if label != _UPCOMING_REFRESH_LABEL or snapshot is None:
            return original_visible_call(app, label, fn, *args, **kwargs)

        # A healthy menu snapshot is already the exact data Upcoming needs. Do not
        # issue a duplicate CalDAV request after the human makes a selection.
        if getattr(snapshot, "warning", None) is None:
            return snapshot

        # If the menu was built while CalDAV was unavailable, selecting Upcoming is
        # a useful explicit retry. A repeated timeout still stays inside the CLI and
        # returns the clearly marked degraded snapshot instead of a traceback.
        try:
            refreshed = original_visible_call(app, label, fn, *args, **kwargs)
        except (UnavailableError, RuntimeError) as exc:
            conversation._show(
                app,
                "Live refresh is still unavailable. The console remains usable; "
                "showing the last available menu snapshot.",
            )
            return _unavailable_snapshot(conversation, app, exc)
        menu_state["snapshot"] = refreshed
        return refreshed

    def guarded_home_menu(app: Any, snapshot: Any):
        prepared = snapshot
        if prepared is None:
            try:
                prepared = original_visible_call(
                    app,
                    _HOME_REFRESH_LABEL,
                    lambda: _read_snapshot(module, app),
                )
            except (UnavailableError, RuntimeError) as exc:
                prepared = _unavailable_snapshot(conversation, app, exc)
                conversation._show(
                    app,
                    "Live Task/Event data is temporarily unavailable. "
                    "The console is still usable; no Task/Event state was changed.",
                )

        menu_state["snapshot"] = prepared
        try:
            return original_home_menu(app, prepared)
        finally:
            menu_state["snapshot"] = None

    def guarded_execute_user(app: Any, parsed: Any, *, paginate: bool = True):
        if _canonical_shell(app, parsed) is not None:
            return _execute_shell_on_main(module, app, parsed, paginate=paginate)
        return original_execute(app, parsed, paginate=paginate)

    module._read_snapshot = guarded_read_snapshot
    module._execute_user = guarded_execute_user
    conversation._visible_call = guarded_visible_call
    conversation._home_menu = guarded_home_menu
    module._latency_guards_installed = True


__all__ = ["STARTUP_READ_TIMEOUT_SECONDS", "install"]
