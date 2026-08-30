"""Foreground monitor client for the long-running desktop Assistant.

Normal work is passive: after a Task/Event becomes the selected monitor target the
client stops presenting a command prompt and watches the background service's actual
runtime feed. Confirmed reminder delivery rings the terminal bell. Mutating command
progress is streamed from factual Core milestones while the command is still running.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
import sys
from threading import Thread
from time import sleep
from typing import Any, Sequence
from uuid import uuid4

from ...api.v1.errors import ValidationError
from ...api.v1.models import Event, Task
from ..work_period import format_work_duration, maybe_work_duration, parse_work_duration
from . import app as base
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


def _local_deadline(value: Any) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _work_period_text(status: Any) -> str:
    if not isinstance(status, dict):
        return str(status)
    state = str(status.get("state") or "none")
    if state == "none":
        return (
            "No work period is allocated. Task DUE is unchanged. "
            "Use 'work-period 30m' or 'start <task> 30m'."
        )
    if state == "cancelled":
        return (
            f"Work period cancelled ({status.get('cancelled', 0)} reminder(s)). "
            "Storage: assistant_state/reminders.items.v1. Task DUE unchanged."
        )
    duration = int(status.get("duration_seconds", 0) or 0)
    remaining = status.get("remaining_seconds")
    remaining_text = (
        format_work_duration(max(0, int(remaining)))
        if isinstance(remaining, (int, float))
        else "unknown"
    )
    return "\n".join(
        [
            f"Work period: {state}",
            f"Task UID: {status.get('task_id') or '—'}",
            f"Allocated: {format_work_duration(duration)}",
            f"Deadline: {_local_deadline(status.get('deadline'))}",
            f"Remaining: {remaining_text}",
            "Stored as: Assistant explicit reminder -> assistant_state/reminders.items.v1",
            "Task CalDAV DUE/DTSTART: unchanged",
            "At deadline: notify only; Task is NOT auto-completed and NOT auto-paused.",
        ]
    )


def _work_period_command(app: Any, *parts: Any) -> str:
    target = _monitor_target(app)
    task_id = target.object_id if target is not None and target.kind == "task" and target.current_work else None
    if not parts or (len(parts) == 1 and str(parts[0]).strip().casefold() in {"status", "show"}):
        return _work_period_text(_runtime_call(app, "work_period.status", task_id=task_id))
    if len(parts) == 1 and str(parts[0]).strip().casefold() in {"cancel", "stop", "clear"}:
        return _work_period_text(_runtime_call(app, "work_period.cancel", task_id=task_id, reason="user"))
    if len(parts) != 1:
        raise ValidationError("Use: work-period 30m | work-period status | work-period cancel")
    seconds = parse_work_duration(parts[0])
    status = _runtime_call(app, "work_period.allocate", task_id=task_id, seconds=seconds)
    return _work_period_text(status)


def _split_lifecycle_duration(parsed: base.ParsedCommand) -> tuple[base.ParsedCommand, int | None]:
    if parsed.name.casefold() not in {"start", "resume"} or not parsed.args:
        return parsed, None
    seconds = maybe_work_duration(parsed.args[-1])
    if seconds is None:
        return parsed, None
    args = parsed.args[:-1]
    raw = " ".join([parsed.name, *[str(item) for item in args]]).strip()
    return base.ParsedCommand(raw=raw, name=parsed.name, args=args), seconds


def _allocate_after_lifecycle(app: Any, seconds: int) -> bool:
    target = _monitor_target(app)
    if target is None or target.kind != "task" or not target.current_work or not target.object_id:
        _show(app, "Work-period allocation failed: Task lifecycle succeeded, but no current Task could be resolved.")
        return False
    try:
        status = _runtime_call(
            app,
            "work_period.allocate",
            task_id=target.object_id,
            seconds=seconds,
        )
    except Exception as exc:
        _show(app, f"Work-period allocation failed AFTER Task lifecycle succeeded: {type(exc).__name__}: {exc}")
        return False
    _show(app, "")
    _show(app, "=== Work period allocated ===")
    for line in _work_period_text(status).splitlines():
        _show(app, line)
    return True


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
    metadata = dict(event.get("metadata") or {})
    if event.get("source") == "work_period_end":
        _show(app, "")
        _show(app, "Work-period meaning:")
        _show(app, f"  Allocated duration: {format_work_duration(int(metadata.get('duration_seconds', 0) or 0))}")
        _show(app, f"  Deadline: {_local_deadline(metadata.get('deadline') or event.get('scheduled_for'))}")
        _show(app, "  This is NOT the Task DUE date and did not change CalDAV scheduling fields.")
        _show(app, "  The Task remains in progress. Press Ctrl-C to complete or pause it.")
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


def _show_progress(app: Any, event: dict[str, Any]) -> None:
    state = str(event.get("state") or "info")
    prefix = {"started": "→", "done": "✓", "failed": "!"}.get(state, "·")
    _show(app, f"{prefix} {event.get('message') or event.get('stage') or 'Progress'}")


def _execute_visible(app: Any, parsed: base.ParsedCommand, *, paginate: bool = True) -> tuple[int, bool]:
    original = parsed
    parsed, period_seconds = _split_lifecycle_duration(parsed)
    operation_id = uuid4().hex
    cursor = _cursor(app)
    _show(app, "")
    _show(app, "=== Command request ===")
    _show(app, f"Input: {original.raw}")
    _show(app, "Live progress: showing factual Core milestones as they happen.")
    if period_seconds is not None:
        _show(app, f"Work-period request: {format_work_duration(period_seconds)}; separate from Task DUE.")

    result: Queue[tuple[bool, Any]] = Queue(maxsize=1)
    runtime = getattr(app, "runtime", None)

    def worker() -> None:
        original_call = getattr(runtime, "call", None)
        try:
            if callable(original_call):
                def tagged_call(method: str, **payload: Any) -> Any:
                    tagged = dict(payload)
                    tagged.setdefault("__operation_id", operation_id)
                    return original_call(method, **tagged)
                runtime.call = tagged_call
            value = base._execute(app, parsed, paginate=paginate)
            result.put((True, value))
        except BaseException as exc:
            result.put((False, exc))
        finally:
            if callable(original_call):
                runtime.call = original_call

    Thread(
        target=worker,
        name="caldav-assistant-visible-command",
        daemon=True,
    ).start()

    outcome: tuple[bool, Any] | None = None
    while outcome is None:
        try:
            outcome = result.get_nowait()
        except Empty:
            pass
        try:
            for event in _events(app, cursor):
                cursor = max(cursor, int(event.get("seq", cursor) or cursor))
                if event.get("kind") == "operation_progress":
                    if event.get("operation_id") == operation_id:
                        _show_progress(app, event)
                    continue
                target = _monitor_target(app)
                if target is not None:
                    _show_delivery(app, event, target)
        except Exception:
            # Failure to render progress must not interrupt the authoritative call.
            pass
        if outcome is None:
            sleep(0.05)

    # Drain milestones published immediately before the final IPC response.
    try:
        for event in _events(app, cursor):
            cursor = max(cursor, int(event.get("seq", cursor) or cursor))
            if event.get("kind") == "operation_progress" and event.get("operation_id") == operation_id:
                _show_progress(app, event)
    except Exception:
        pass

    ok, value = outcome
    if not ok:
        raise value
    code, should_exit = value
    if code == 0 and period_seconds is not None:
        if not _allocate_after_lifecycle(app, period_seconds):
            code = 1
    _show(app, "=== Command result ===")
    _show(app, f"Exit code: {code}; result: {'success' if code == 0 else 'failed/partial'}")
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
        _show(app, "4. Open console for other functions / work-period")
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
    if target.kind == "task" and target.current_work:
        try:
            status = _runtime_call(app, "work_period.status", task_id=target.object_id)
            if isinstance(status, dict) and status.get("state") != "none":
                _show(app, _work_period_text(status))
        except Exception as exc:
            _show(app, f"Work-period status unavailable: {type(exc).__name__}: {exc}")
    _show(app, "No command prompt is active now.")
    _show(app, "Background service is watching reminders/events independently.")
    _show(app, "A confirmed reminder delivery rings the terminal bell (\\a) and is printed here.")
    _show(app, "Live delivery feed: bounded in-memory runtime data; Task/Event and Activity/Work Log remain the persistent records.")
    _show(app, "Press Ctrl-C to complete/pause/manage this item or open the console.")

    while True:
        try:
            for event in _events(app, cursor):
                cursor = max(cursor, int(event.get("seq", cursor) or cursor))
                if event.get("kind") == "operation_progress":
                    continue
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
    entered_with_target = _monitor_target(app) is not None
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

        if not entered_with_target and code == 0 and _monitor_target(app) is not None:
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
    if runtime is not None and "work-period" not in app.commands.registry:
        app.commands.register_builtin(
            "work-period",
            lambda *parts: _work_period_command(app, *parts),
            aliases=("timer",),
            description=(
                "Set/show/cancel the current Task's work-period deadline. "
                "Example: work-period 30m. This never changes Task DUE."
            ),
        )

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
        parsed = base.ParsedCommand(
            raw=" ".join(str(item) for item in argv),
            name=str(argv[0]).strip(),
            args=tuple(str(item) for item in argv[1:]),
        )
        effective, seconds = _split_lifecycle_duration(parsed)
        if seconds is not None or effective.name.casefold() in {"start", "pause", "resume", "done", "complete"}:
            code, _ = _execute_visible(app, parsed, paginate=False)
            return code
        return base.run_one_shot(app, argv)
    with completion_session(app):
        return run_monitor_repl(app)
