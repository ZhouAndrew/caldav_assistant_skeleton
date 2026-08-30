"""Foreground monitor client for the long-running desktop Assistant.

Normal work is passive: after a Task/Event becomes the selected monitor target the
client stops presenting a command prompt and watches the background service's actual
notification-delivery feed.  Every delivered reminder rings the terminal bell (\a)
and prints what was accessed, what happened, and the confirmed result.

Ctrl-C does not kill the Assistant while monitoring.  It opens a small action menu;
Task lifecycle choices are sent through the existing CommandService/Core API.  The
ordinary console is a separate mode for other commands.
"""
from __future__ import annotations

from dataclasses import dataclass
import shlex
import sys
from time import sleep
from typing import Any, Sequence

from ...api.v1.models import Event, Task
from . import app as base
from .actions import EXIT_REPL
from .completion import completion_session


@dataclass(frozen=True, slots=True)
class MonitorTarget:
    kind: str
    object_id: str | None
    summary: str
    value: Any
    current_work: bool = False

    @property
    def key(self) -> tuple[str, str | None, bool]:
        return self.kind, self.object_id, self.current_work


def _summary(value: Any) -> str:
    text = str(getattr(value, "summary", "") or "").strip()
    if text:
        return text
    uid = str(getattr(value, "id", "") or "").strip()
    return uid or value.__class__.__name__


def _monitor_target(app: Any) -> MonitorTarget | None:
    session = getattr(app.ctx, "session", None)
    current = getattr(session, "current_task", None)
    if callable(current):
        try:
            task = current()
        except Exception:
            task = None
        if task is not None:
            return MonitorTarget(
                "task",
                str(getattr(task, "id", "") or "").strip() or None,
                _summary(task),
                task,
                True,
            )

    selected = getattr(session, "current_selection", None) if session is not None else None
    if isinstance(selected, Task):
        return MonitorTarget(
            "task",
            str(getattr(selected, "id", "") or "").strip() or None,
            _summary(selected),
            selected,
            False,
        )
    if isinstance(selected, Event):
        return MonitorTarget(
            "event",
            str(getattr(selected, "id", "") or "").strip() or None,
            _summary(selected),
            selected,
            False,
        )
    return None


def _runtime_call(app: Any, method: str, **payload: Any) -> Any:
    runtime = getattr(app, "runtime", None)
    call = getattr(runtime, "call", None)
    if not callable(call):
        raise RuntimeError("This client has no background Runtime connection")
    try:
        return call(method, **payload)
    except RuntimeError as exc:
        # A pre-update daemon can still be serving the old route table.  Restart it
        # once so the foreground never silently falls back to fake local monitoring.
        if f"IPC method is not allowed: {method}" not in str(exc):
            raise
        restart = getattr(runtime, "restart", None)
        if not callable(restart):
            raise
        restart()
        return call(method, **payload)


def _cursor(app: Any) -> int:
    value = _runtime_call(app, "runtime.events.cursor")
    if isinstance(value, dict):
        return int(value.get("cursor", 0) or 0)
    return 0


def _events(app: Any, after: int) -> list[dict[str, Any]]:
    value = _runtime_call(app, "runtime.events.list", after=int(after), limit=50)
    return [item for item in (value or ()) if isinstance(item, dict)]


def _bell(app: Any) -> None:
    io = getattr(app, "io", None)
    stream = getattr(io, "stdout", None)
    if stream is not None and callable(getattr(stream, "write", None)):
        stream.write("\a")
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()
        return
    write = getattr(io, "write", None)
    if callable(write):
        write("\a")


def _show(app: Any, value: Any = "") -> None:
    base._ui_show(app, value)


def _show_delivery(app: Any, event: dict[str, Any], target: MonitorTarget) -> None:
    _bell(app)
    _show(app, "")
    _show(app, "=== Reminder actually delivered ===")
    _show(app, f"Occurred: {event.get('occurred_at') or 'unknown'}")
    _show(app, f"Source: {event.get('source') or 'reminder'}")
    if event.get("object_id"):
        _show(app, f"Object id: {event['object_id']}")
    _show(app, f"Notification: {event.get('title') or '(untitled)'}")
    if event.get("body"):
        _show(app, f"Detail: {event['body']}")
    _show(app, "")
    _show(app, "Program access / operation / result:")
    _show(app, "  1. Foreground read: Local IPC -> runtime.events.list (read-only).")
    _show(app, "  2. Background operation: ReminderService.process_due().")
    adapter = event.get("adapter") or "configured NotificationAdapter"
    _show(app, f"  3. Delivery: NotificationService -> {adapter}.")
    _show(app, "  4. Reminder delivery key: persisted before this feed event was published.")
    _show(app, f"  5. Result: {event.get('result') or 'delivered'}.")
    _show(app, "  6. Task/Event state: unchanged by the reminder itself.")
    _show(app, f"Still monitoring {target.kind}: {target.summary}")


def _primary_route(name: str) -> str:
    key = name.casefold()
    routes = {
        "start": "CLI -> CommandService -> Local IPC -> TaskService.start -> CalDAV/Activity/WorkLog",
        "done": "CLI -> CommandService -> Local IPC -> TaskService.complete -> CalDAV/Activity/WorkLog",
        "complete": "CLI -> CommandService -> Local IPC -> TaskService.complete -> CalDAV/Activity/WorkLog",
        "pause": "CLI -> CommandService -> Local IPC -> TaskService.pause -> Activity/WorkLog",
        "resume": "CLI -> CommandService -> Local IPC -> TaskService.resume -> CalDAV/Activity/WorkLog",
        "today": "CLI -> CommandService -> Local IPC -> AgendaService.today -> Task/Event read path",
        "next": "CLI -> CommandService -> Local IPC -> AgendaService.next -> Task/Event read path",
        "current": "CLI -> CommandService -> Session current-task read",
        "now": "CLI -> CommandService -> Session current-task read",
        "edit": "CLI -> CommandService -> Local IPC -> TaskService.update -> CalDAV/Activity",
        "settings": "CLI -> Settings client -> Local IPC -> Settings/CalDAV setup services",
        "history": "CLI -> history provider -> Activity/WordPress/Outbox read path",
    }
    return routes.get(key, "CLI -> CommandService -> configured Core/public API route")


def _execute_visible(app: Any, parsed: base.ParsedCommand, *, paginate: bool = True) -> tuple[int, bool]:
    _show(app, "")
    _show(app, "=== Command request ===")
    _show(app, f"Input: {parsed.raw}")
    _show(app, f"Primary access path: {_primary_route(parsed.name)}")
    code, should_exit = base._execute(app, parsed, paginate=paginate)
    _show(app, "=== Command result ===")
    _show(app, f"Exit code: {code}; result: {'success' if code == 0 else 'failed'}")
    return code, should_exit


def _parsed(name: str, *args: Any) -> base.ParsedCommand:
    raw = " ".join([name, *[str(item) for item in args]]).strip()
    return base.ParsedCommand(raw=raw, name=name, args=tuple(args))


def _read_choice(app: Any, prompt: str = "Choice: ") -> str:
    return str(app.io.read(prompt)).strip().casefold()


def _interrupt_menu(app: Any, target: MonitorTarget) -> str:
    _show(app, "")
    _show(app, f"Monitoring interrupted: {target.kind} — {target.summary}")
    if target.kind == "task" and target.current_work:
        _show(app, "1. Complete this Task")
        _show(app, "2. Pause current work")
        _show(app, "3. Continue monitoring")
        _show(app, "4. Open console for other functions")
        _show(app, "5. Exit client (background service keeps running)")
        choice = _read_choice(app)
        if choice in {"1", "done", "complete"}:
            _execute_visible(app, _parsed("done"), paginate=False)
            return "recheck"
        if choice in {"2", "pause"}:
            _execute_visible(app, _parsed("pause"), paginate=False)
            return "recheck"
        if choice in {"4", "console", "c"}:
            return "console"
        if choice in {"5", "exit", "q"}:
            return "exit"
        return "monitor"

    if target.kind == "task":
        _show(app, "1. Start working on this Task")
        _show(app, "2. Mark this Task complete")
        _show(app, "3. Continue monitoring")
        _show(app, "4. Open console for other functions")
        _show(app, "5. Stop watching this selection")
        _show(app, "6. Exit client")
        choice = _read_choice(app)
        if choice in {"1", "start"}:
            _execute_visible(app, _parsed("start", target.value), paginate=False)
            return "recheck"
        if choice in {"2", "done", "complete"}:
            _execute_visible(app, _parsed("done", target.value), paginate=False)
            return "recheck"
        if choice in {"4", "console", "c"}:
            return "console"
        if choice in {"5", "stop"}:
            app.ctx.session.current_selection = None
            return "recheck"
        if choice in {"6", "exit", "q"}:
            return "exit"
        return "monitor"

    _show(app, "1. Continue monitoring")
    _show(app, "2. Open console for other functions")
    _show(app, "3. Stop watching this Event")
    _show(app, "4. Exit client")
    choice = _read_choice(app)
    if choice in {"2", "console", "c"}:
        return "console"
    if choice in {"3", "stop"}:
        app.ctx.session.current_selection = None
        return "recheck"
    if choice in {"4", "exit", "q"}:
        return "exit"
    return "monitor"


def _monitor(app: Any, target: MonitorTarget) -> str:
    cursor = _cursor(app)
    _show(app, "")
    _show(app, f"Monitoring {target.kind}: {target.summary}")
    _show(app, "No command prompt is active now.")
    _show(app, "Background service is watching reminders/events independently.")
    _show(app, "A confirmed reminder delivery rings the terminal bell (\\a) and is printed here.")
    _show(app, "Press Ctrl-C to complete/pause/manage this item or open the console.")

    while True:
        try:
            for event in _events(app, cursor):
                cursor = max(cursor, int(event.get("seq", cursor) or cursor))
                _show_delivery(app, event, target)

            if target.current_work:
                current = getattr(app.ctx.session, "current_task", lambda: None)()
                current_id = str(getattr(current, "id", "") or "").strip() or None
                if current_id != target.object_id:
                    return "recheck"
            sleep(0.5)
        except KeyboardInterrupt:
            return _interrupt_menu(app, target)


def _console(app: Any) -> tuple[int, str]:
    _show(app, "")
    _show(app, "Console mode: use commands for other functions.")
    _show(app, "Type 'monitor' to return to passive monitoring when a target exists.")
    last_code = 0
    while True:
        target = _monitor_target(app)
        label = f"[console | {target.summary}] > " if target is not None else "> "
        try:
            line = app.io.read(label)
        except EOFError:
            return last_code, "exit"
        except KeyboardInterrupt:
            _show(app, "")
            return last_code, "monitor" if target is not None else "console"

        raw = str(line).strip()
        if raw.casefold() == "monitor":
            return last_code, "monitor"
        try:
            parsed = base.parse_command_line(line)
        except ValueError as exc:
            base._error(app, base._t(app, "cli.invalid_input", "Invalid input: {error}", error=exc))
            last_code = 2
            continue
        if parsed is None:
            parsed = base._guided_menu_command(app)
            if parsed is None:
                continue
        code, should_exit = _execute_visible(app, parsed, paginate=True)
        last_code = code
        if should_exit:
            return code, "exit"

        # A successful command may have selected an Event/Task or started work.
        # Follow the human model: once there is a concrete target, go passive.
        if code == 0 and _monitor_target(app) is not None:
            return last_code, "monitor"


def run_monitor_repl(app: Any) -> int:
    _show(app, "CalDAV Assistant")
    _show(app, "Model: select/start an item -> passive monitor; Ctrl-C -> decision; console -> other functions.")
    base._emit_repl_started(app)
    last_code = 0

    while True:
        target = _monitor_target(app)
        if target is None:
            last_code, action = _console(app)
        else:
            action = _monitor(app, target)

        if action == "exit":
            return last_code
        if action == "console":
            last_code, action = _console(app)
            if action == "exit":
                return last_code
        # monitor/recheck both simply recompute the authoritative/local selection.


def _prepare(app: Any, argv: Sequence[str]) -> None:
    base.register_cli_builtin_commands(app.commands, app.ctx)
    base.register_crud_cli_commands(app.commands, app.ctx)
    base.register_navigation_cli_commands(app.commands, app.ctx)
    base.register_api_cli_command(app.commands)

    if "settings" not in app.commands.registry:
        base.register_settings_cli_command(app.commands, app.ctx)

    runtime = getattr(app, "runtime", None)
    if runtime is not None and "background" not in app.commands.registry:
        base.register_background_cli_command(app.commands, runtime, ui=app.ctx.ui)
    if runtime is not None and "undo" not in app.commands.registry:
        base.register_undo_cli_command(app.commands, runtime)

    local_background_command = bool(argv and str(argv[0]).strip().casefold() == "background")
    if app.extensions is not None:
        base.register_extension_cli_commands(app.commands, app.extensions)
        if not local_background_command:
            app.extensions.load_enabled()


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if app is None:
        from ..bootstrap import build_cli_application

        app = build_cli_application()

    _prepare(app, argv)
    if argv:
        # One-shot commands remain one-shot; monitor mode is an interactive-client UX.
        return base.run_one_shot(app, argv)
    with completion_session(app):
        return run_monitor_repl(app)


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MonitorTarget", "run_monitor_repl", "run_cli", "main"]
