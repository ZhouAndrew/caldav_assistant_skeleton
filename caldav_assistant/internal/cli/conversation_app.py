"""Zero-learning terminal conversation client.

This is a presentation/composition layer only. Task/Event truth and lifecycle remain in
Core/CalDAV, work-period persistence remains in the background ReminderService, and
all canonical commands still terminate at CommandService.  The client adds the human
path requested by the product design: welcome -> upcoming -> recommendation -> one
console, plus guided Task+duration start and a live, non-blocking waiting view.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import math
import os
import select
import sys
from threading import Thread
from time import monotonic, sleep
from typing import Any, Callable, Sequence

from ...api.v1.errors import CalDAVAssistantError, ValidationError
from ...api.v1.models import Agenda, AgendaItem, Event, Task
from ..settings.keys import AGENDA_UPCOMING_HOURS
from ..work_period import format_work_duration, maybe_work_duration, parse_work_duration
from . import app as base
from . import monitor_app as legacy
from .completion import completion_session


DEFAULT_UPCOMING_HOURS = 24


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    current_task: Any = None
    upcoming: tuple[AgendaItem, ...] = ()
    recommended: Any = None
    window_hours: int = DEFAULT_UPCOMING_HOURS
    warning: str | None = None


def _show(app: Any, value: Any = "") -> None:
    base._ui_show(app, value)


def _summary(value: Any) -> str:
    text = str(getattr(value, "summary", "") or "").strip()
    if text:
        return text
    return str(getattr(value, "id", "") or value.__class__.__name__)


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone()
    return value.astimezone()


def _clock(value: Any) -> str:
    if isinstance(value, datetime):
        return _local(value).strftime("%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return "—"


def _short_when(value: Any) -> str:
    if isinstance(value, datetime):
        local = _local(value)
        today = datetime.now().astimezone().date()
        prefix = "today " if local.date() == today else local.strftime("%m-%d ")
        return prefix + local.strftime("%H:%M")
    if isinstance(value, date):
        today = datetime.now().astimezone().date()
        if value == today:
            return "today"
        if value == today + timedelta(days=1):
            return "tomorrow"
        return value.isoformat()
    return "unscheduled"


def _window_hours(app: Any) -> int:
    settings = getattr(app.ctx, "settings", None)
    getter = getattr(settings, "get", None)
    if not callable(getter):
        return DEFAULT_UPCOMING_HOURS
    try:
        value = int(getter(AGENDA_UPCOMING_HOURS, DEFAULT_UPCOMING_HOURS))
    except (TypeError, ValueError, CalDAVAssistantError):
        return DEFAULT_UPCOMING_HOURS
    return min(24 * 31, max(1, value))


def _item_in_window(item: AgendaItem, now: datetime, end: datetime) -> bool:
    when = getattr(item, "when", None)
    if isinstance(when, datetime):
        point = _local(when)
        return now <= point <= end
    if isinstance(when, date):
        return now.date() <= when <= end.date()
    return False


def _read_snapshot(app: Any) -> StartupSnapshot:
    hours = _window_hours(app)
    now = datetime.now().astimezone()
    end = now + timedelta(hours=hours)

    session = getattr(app.ctx, "session", None)
    current_getter = getattr(session, "current_task", None)
    current = current_getter() if callable(current_getter) else None

    days = max(1, int(math.ceil(hours / 24.0)) + 1)
    agenda = app.ctx.agenda.range(days=days)
    values = tuple(
        item for item in getattr(agenda, "items", ()) if _item_in_window(item, now, end)
    )

    try:
        recommendation = app.ctx.agenda.next(kind="task")
    except TypeError:
        recommendation = app.ctx.agenda.next()
    recommendation = getattr(recommendation, "value", recommendation)
    if recommendation is not None:
        if bool(getattr(recommendation, "completed", False)) or str(
            getattr(recommendation, "status", "")
        ) == "CANCELLED":
            recommendation = None

    return StartupSnapshot(
        current_task=current,
        upcoming=values,
        recommended=recommendation,
        window_hours=hours,
    )


def _visible_call(
    app: Any,
    label: str,
    fn: Callable[[], Any],
    *,
    heartbeat_after: float = 2.0,
) -> Any:
    """Run a non-interactive read with truthful heartbeat output.

    Startup reads are safe to run in a worker because they never prompt.  The main
    thread remains responsible for terminal output, so a slow CalDAV/IPC read cannot
    look like a dead process. No made-up percentage is shown.
    """
    _show(app, label)
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised on the UI thread
            box["error"] = exc

    started = monotonic()
    thread = Thread(target=worker, name="caldav-assistant-visible-read", daemon=True)
    thread.start()
    next_heartbeat = heartbeat_after
    while thread.is_alive():
        thread.join(timeout=0.2)
        elapsed = monotonic() - started
        if thread.is_alive() and elapsed >= next_heartbeat:
            _show(app, f"  Still working… {int(elapsed)}s elapsed")
            next_heartbeat += 3.0

    elapsed = monotonic() - started
    if "error" in box:
        error = box["error"]
        _show(app, f"✗ {label.rstrip('.…')} failed: {type(error).__name__}: {error}")
        raise error
    _show(app, f"✓ Done ({elapsed:.1f}s)")
    return box.get("value")


def _greeting() -> str:
    hour = datetime.now().astimezone().hour
    if 5 <= hour < 12:
        return "Good morning."
    if 12 <= hour < 18:
        return "Good afternoon."
    if 18 <= hour < 23:
        return "Good evening."
    return "Hello."


def _render_upcoming_item(item: AgendaItem) -> str:
    value = getattr(item, "value", None)
    kind = str(getattr(item, "kind", "") or "").casefold()
    icon = "◷" if isinstance(value, Event) or kind == "event" else "□"
    when = getattr(item, "when", None)
    return f"  {icon} {_summary(value)} — {_short_when(when)}"


def _snapshot_text(snapshot: StartupSnapshot) -> str:
    lines = [f"Upcoming · next {snapshot.window_hours}h"]
    if not snapshot.upcoming:
        lines.append("  (nothing scheduled in this window)")
    else:
        for item in snapshot.upcoming[:10]:
            lines.append(_render_upcoming_item(item))
        if len(snapshot.upcoming) > 10:
            lines.append(f"  … and {len(snapshot.upcoming) - 10} more")
    return "\n".join(lines)


def _show_welcome(app: Any) -> StartupSnapshot:
    _show(app, "CalDAV Assistant")
    _show(app, _greeting())
    _show(app, "")
    try:
        snapshot = _visible_call(app, "Reading current work, Tasks and Events…", lambda: _read_snapshot(app))
    except Exception as exc:
        snapshot = StartupSnapshot(
            window_hours=_window_hours(app),
            warning=f"Live agenda is unavailable: {type(exc).__name__}: {exc}",
        )

    _show(app, "")
    _show(app, "Now")
    if snapshot.current_task is None:
        _show(app, "  No Task is currently being worked on.")
    else:
        _show(app, f"  ▶ {_summary(snapshot.current_task)}")

    _show(app, "")
    _show(app, _snapshot_text(snapshot))

    _show(app, "")
    _show(app, "Recommended")
    if snapshot.recommended is None:
        _show(app, "  No actionable Task is recommended right now.")
    else:
        task = snapshot.recommended
        due = getattr(task, "due", None)
        detail = f" — due {_short_when(due)}" if due is not None else ""
        _show(app, f"  → {_summary(task)}{detail}")

    if snapshot.warning:
        _show(app, "")
        _show(app, f"Warning: {snapshot.warning}")
        _show(app, "The Assistant will not pretend that unavailable live data is current.")

    _show(app, "")
    _show(app, "Press Enter for the guided menu, or type a command directly.")
    _show(app, "Guide Book: guide    Developing Docs: dev    Help: help")
    return snapshot


def _duration_choice(app: Any) -> int | None | bool:
    choose = getattr(app.ctx.ui, "choose", None)
    if not callable(choose):
        raise ValidationError("Guided start requires interactive UI")
    labels = (
        "15 minutes",
        "25 minutes",
        "30 minutes",
        "45 minutes",
        "60 minutes",
        "Custom duration",
        "No planned end time",
    )
    selected = choose(
        "How long do you want to work?",
        labels,
        help_text=(
            "This is a work period, not the Task DUE date. When the time ends the "
            "Assistant reminds you; it never auto-completes the Task."
        ),
    )
    if selected is None:
        return False
    fixed = {
        "15 minutes": 15 * 60,
        "25 minutes": 25 * 60,
        "30 minutes": 30 * 60,
        "45 minutes": 45 * 60,
        "60 minutes": 60 * 60,
    }
    if selected in fixed:
        return fixed[selected]
    if selected == "No planned end time":
        return None
    ask = getattr(app.ctx.ui, "ask_text", None)
    if not callable(ask):
        raise ValidationError("Custom work period requires text input")
    value = ask("Duration (for example 40m or 1h)")
    if value is None:
        return False
    return parse_work_duration(value)


def _period_plan_text(task: Any, seconds: int | None) -> str:
    now = datetime.now().astimezone()
    lines = [f"Task: {_summary(task)}", f"Start: {now.strftime('%H:%M:%S')}"]
    if seconds is None:
        lines.extend(["Planned end: not set", "Duration: open-ended"])
    else:
        end = now + timedelta(seconds=seconds)
        lines.extend(
            [
                f"Planned end: {end.strftime('%H:%M:%S')}",
                f"Duration: {format_work_duration(seconds)}",
            ]
        )
    return "\n".join(lines)


def _execute_user(app: Any, parsed: base.ParsedCommand, *, paginate: bool = True) -> tuple[int, bool]:
    """Execute one canonical command with human progress, not developer plumbing."""
    original = parsed
    effective, period_seconds = legacy._split_lifecycle_duration(parsed)
    _show(app, "")
    _show(app, f"Working: {original.raw}")
    started = monotonic()
    code, should_exit = base._execute(app, effective, paginate=paginate)

    if code == 0 and period_seconds is not None:
        target = legacy._monitor_target(app)
        if target is None or target.kind != "task" or not target.current_work or not target.object_id:
            _show(app, "✗ Task started, but the Assistant could not resolve the current Task for its work period.")
            code = 1
        else:
            _show(app, "Setting the work-period reminder in the background Assistant…")
            try:
                status = legacy._runtime_call(
                    app,
                    "work_period.allocate",
                    task_id=target.object_id,
                    seconds=period_seconds,
                )
            except Exception as exc:
                _show(app, f"✗ Task lifecycle succeeded, but work-period setup failed: {type(exc).__name__}: {exc}")
                code = 1
            else:
                deadline = status.get("deadline") if isinstance(status, dict) else None
                remaining = status.get("remaining_seconds") if isinstance(status, dict) else None
                _show(app, "✓ Work period is active.")
                _show(app, f"  Planned end: {_clock(datetime.fromisoformat(deadline)) if deadline else 'unknown'}")
                if isinstance(remaining, (int, float)):
                    _show(app, f"  Remaining: {format_work_duration(max(0, int(remaining)))}")
                _show(app, "  Task DUE/DTSTART were not changed.")

    elapsed = monotonic() - started
    if code == 0:
        _show(app, f"✓ Operation finished ({elapsed:.1f}s)")
    else:
        _show(app, f"✗ Operation did not fully succeed ({elapsed:.1f}s)")
    return code, should_exit


def _guided_start(app: Any, task: Any = None) -> str:
    session = getattr(app.ctx, "session", None)
    current_getter = getattr(session, "current_task", None)
    current = current_getter() if callable(current_getter) else None
    if current is not None:
        _show(app, f"You are already working on: {_summary(current)}")
        _show(app, "Pause or complete it before starting another Task.")
        return "wait"

    if task is None:
        chooser = getattr(app.ctx.ui, "choose_task", None)
        if not callable(chooser):
            raise ValidationError("Guided start requires Task selection")
        task = chooser(title="Choose a Task to work on")
    if task is None:
        return "console"

    seconds = _duration_choice(app)
    if seconds is False:
        return "console"

    _show(app, "")
    _show(app, "Ready to start")
    _show(app, _period_plan_text(task, seconds))
    confirm = getattr(app.ctx.ui, "confirm", None)
    if callable(confirm) and not confirm("Start now?", default=True):
        return "console"

    args: tuple[Any, ...]
    if seconds is None:
        args = (task,)
    else:
        args = (task, f"{int(seconds)}s")
    parsed = base.ParsedCommand(raw=f"start {_summary(task)}" + (f" {seconds}s" if seconds else ""), name="start", args=args)
    code, should_exit = _execute_user(app, parsed, paginate=False)
    if should_exit:
        return "exit"
    return "wait" if code == 0 else "console"


def _configure_upcoming(app: Any) -> int | None:
    choose = getattr(app.ctx.ui, "choose", None)
    if not callable(choose):
        raise ValidationError("Upcoming setup requires interactive UI")
    current = _window_hours(app)
    selected = choose(
        f"Upcoming window · currently {current}h",
        (
            "12 hours",
            "24 hours",
            "Today + tomorrow (48h)",
            "3 days (72h)",
            "7 days (168h)",
            "Custom hours",
        ),
        help_text=(
            "Upcoming means Task/Event agenda items whose effective time falls inside "
            "this future window. Overdue items are not silently relabelled as Upcoming."
        ),
    )
    if selected is None:
        return None
    mapping = {
        "12 hours": 12,
        "24 hours": 24,
        "Today + tomorrow (48h)": 48,
        "3 days (72h)": 72,
        "7 days (168h)": 168,
    }
    if selected in mapping:
        hours = mapping[selected]
    else:
        ask = getattr(app.ctx.ui, "ask_text", None)
        if not callable(ask):
            raise ValidationError("Custom Upcoming window requires text input")
        raw = ask("Upcoming hours (1-744)")
        if raw is None:
            return None
        try:
            hours = int(str(raw).strip())
        except ValueError as exc:
            raise ValidationError("Upcoming hours must be a whole number") from exc
    normalized = app.ctx.settings.set(AGENDA_UPCOMING_HOURS, hours)
    _show(app, f"✓ Upcoming window: next {normalized}h")
    _show(app, "Saved in Assistant settings; CalDAV Task/Event data were not changed.")
    return int(normalized)


def _upcoming_command(app: Any, *parts: Any) -> Any:
    if not parts:
        snapshot = _visible_call(app, "Reading Upcoming Tasks and Events…", lambda: _read_snapshot(app))
        return _snapshot_text(snapshot)
    action = str(parts[0]).strip().casefold()
    if action in {"setup", "configure", "config"}:
        if len(parts) != 1:
            raise ValidationError("Use: upcoming setup")
        return _configure_upcoming(app)
    if action == "set":
        if len(parts) != 2:
            raise ValidationError("Use: upcoming set HOURS")
        try:
            hours = int(str(parts[1]).strip())
        except ValueError as exc:
            raise ValidationError("Upcoming hours must be a whole number") from exc
        normalized = app.ctx.settings.set(AGENDA_UPCOMING_HOURS, hours)
        return f"✓ Upcoming window: next {normalized}h"
    raise ValidationError("Use: upcoming | upcoming setup | upcoming set HOURS")


def _guide_book(app: Any, *parts: Any) -> Any:
    topics = {
        "30-second quick start": (
            "Quick start\n"
            "1. Run caldav-assistant.\n"
            "2. Read Now / Upcoming / Recommended.\n"
            "3. Press Enter, choose a Task, choose a work duration, and Start.\n"
            "4. Waiting Mode shows start/end/remaining time.\n"
            "5. p=pause, d=complete, c=console, q=leave client (background keeps running)."
        ),
        "Upcoming and recommendations": (
            "Upcoming is your configurable future window (default 24h).\n"
            "Use `upcoming setup` to change it. Recommendation comes from Agenda/Next; "
            "it does not create or rewrite a Task."
        ),
        "Start / pause / resume / complete": (
            "start = begin real work on a Task now.\n"
            "pause = stop the current work interval without completing the Task.\n"
            "resume = continue previously paused work.\n"
            "done = mark a Task COMPLETED in CalDAV. Events do not use these lifecycle verbs."
        ),
        "Waiting Mode": (
            "A work period is Assistant-owned timing, separate from Task DUE/DTSTART.\n"
            "The background Assistant keeps the deadline if the terminal closes.\n"
            "When time expires, it reminds you; it never auto-completes or auto-pauses the Task."
        ),
        "Task and Event management": (
            "Press Enter -> Task / Event management, or use add/tasks/events/edit/edit-event/remove.\n"
            "All writes go through the same Core services and authoritative CalDAV path."
        ),
        "Logs and storage": (
            "Task/Event truth: CalDAV. Assistant timing/activity: local Assistant state/Activity Journal.\n"
            "Long-form logs: WordPress; failed uploads stay in Outbox."
        ),
    }
    if parts:
        query = " ".join(str(item) for item in parts).strip().casefold()
        for name, text in topics.items():
            if query in name.casefold():
                return text
        raise ValidationError("Unknown Guide Book topic")

    choose = getattr(app.ctx.ui, "choose", None)
    if not callable(choose):
        return "Guide Book\n" + "\n".join(f"- {name}" for name in topics)
    while True:
        selected = choose("Guide Book", tuple(topics))
        if selected is None:
            return None
        _show(app, "")
        _show(app, topics[str(selected)])
        _show(app, "")


def _developing_docs(app: Any, *parts: Any) -> Any:
    if parts:
        query = " ".join(str(item) for item in parts).strip()
        return app.ctx.commands.run("api", query)
    choose = getattr(app.ctx.ui, "choose", None)
    if not callable(choose):
        return app.ctx.commands.run("api")
    while True:
        selected = choose(
            "Developing Docs",
            (
                "Public API overview",
                "Easy API",
                "Object API",
                "Full Extension API v1",
                "Search Public API",
                "Extension guide",
            ),
            help_text="These docs describe the real exported Public API; Internal is not a compatibility promise.",
        )
        if selected is None:
            return None
        if selected == "Public API overview":
            _show(app, app.ctx.commands.run("api"))
        elif selected == "Easy API":
            _show(app, app.ctx.commands.run("api", "list", "easy"))
        elif selected == "Object API":
            _show(app, app.ctx.commands.run("api", "list", "object"))
        elif selected == "Full Extension API v1":
            _show(app, app.ctx.commands.run("api", "list", "full"))
        elif selected == "Search Public API":
            ask = getattr(app.ctx.ui, "ask_text", None)
            query = ask("Search Public API") if callable(ask) else None
            if query:
                _show(app, app.ctx.commands.run("api", "search", str(query)))
        else:
            _show(app, app.ctx.commands.run("extension", "guide"))


def _register_conversation_commands(app: Any) -> None:
    existing = set(app.commands.names(include_aliases=True))
    specs = (
        ("home", lambda: _home_menu(app, None), ("welcome",), "Open the zero-learning Assistant home menu."),
        ("upcoming", lambda *parts: _upcoming_command(app, *parts), (), "Show/configure the user-defined Upcoming window."),
        ("guide", lambda *parts: _guide_book(app, *parts), ("guidebook",), "Open the integrated user Guide Book."),
        ("dev", lambda *parts: _developing_docs(app, *parts), ("developing",), "Open integrated developer/Public API documentation."),
    )
    for name, handler, aliases, description in specs:
        if name in existing:
            continue
        safe_aliases = tuple(alias for alias in aliases if alias not in existing)
        app.commands.register_builtin(name, handler, aliases=safe_aliases, description=description)
        existing.add(name)
        existing.update(safe_aliases)


def _home_menu(app: Any, snapshot: StartupSnapshot | None) -> str:
    if snapshot is None:
        try:
            snapshot = _read_snapshot(app)
        except Exception:
            snapshot = StartupSnapshot(window_hours=_window_hours(app))
    choose = getattr(app.ctx.ui, "choose", None)
    if not callable(choose):
        return "console"

    current = snapshot.current_task
    labels: list[str] = []
    if current is not None:
        labels.append(f"Return to Waiting Mode — {_summary(current)}")
    if snapshot.recommended is not None and current is None:
        labels.append(f"Start recommended Task — {_summary(snapshot.recommended)}")
    if current is None:
        labels.append("Choose a Task and start")
    labels.extend(
        [
            f"Upcoming — next {snapshot.window_hours}h",
            "Today",
            "Task / Event management",
            "Logs and history",
            "Guide Book",
            "Developing Docs",
            "Upcoming settings",
            "Settings and setup",
            "Stay in console",
        ]
    )
    selected = choose(
        "What do you want to do?",
        tuple(labels),
        help_text="Choose by number. You can also leave this menu and type canonical commands directly.",
    )
    if selected is None or selected == "Stay in console":
        return "console"
    text = str(selected)
    if text.startswith("Return to Waiting Mode"):
        return "wait"
    if text.startswith("Start recommended Task"):
        return _guided_start(app, snapshot.recommended)
    if text == "Choose a Task and start":
        return _guided_start(app)
    if text.startswith("Upcoming —"):
        _show(app, _snapshot_text(_visible_call(app, "Refreshing Upcoming…", lambda: _read_snapshot(app))))
        return "console"
    if text == "Today":
        _execute_user(app, base.ParsedCommand(raw="today", name="today", args=()))
        return "console"
    if text == "Task / Event management":
        _execute_user(app, base.ParsedCommand(raw="menu", name="menu", args=()))
        return "console"
    if text == "Logs and history":
        _execute_user(app, base.ParsedCommand(raw="history", name="history", args=()))
        return "console"
    if text == "Guide Book":
        _guide_book(app)
        return "console"
    if text == "Developing Docs":
        _developing_docs(app)
        return "console"
    if text == "Upcoming settings":
        _configure_upcoming(app)
        return "console"
    if text == "Settings and setup":
        _execute_user(app, base.ParsedCommand(raw="settings", name="settings", args=()))
        return "console"
    return "console"


def _work_period_status(app: Any, target: legacy.MonitorTarget) -> dict[str, Any]:
    if not target.object_id:
        return {"state": "none"}
    try:
        value = legacy._runtime_call(app, "work_period.status", task_id=target.object_id)
    except Exception as exc:
        return {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
    return dict(value) if isinstance(value, dict) else {"state": "none"}


def _actual_work_start(app: Any, task: Any) -> datetime | None:
    reader = getattr(getattr(app.ctx, "activity", None), "for_task", None)
    if not callable(reader):
        return None
    try:
        items = list(reader(task) or ())
    except Exception:
        return None
    lifecycle = [
        item
        for item in items
        if getattr(item, "action", None) in {"task_started", "task_resumed", "task_paused", "task_completed"}
        and isinstance(getattr(item, "timestamp", None), datetime)
    ]
    if not lifecycle:
        return None
    latest = max(lifecycle, key=lambda item: getattr(item, "timestamp"))
    if getattr(latest, "action", None) not in {"task_started", "task_resumed"}:
        return None
    return _local(getattr(latest, "timestamp"))


def _deadline_info(status: dict[str, Any]) -> tuple[datetime | None, int | None]:
    deadline_raw = status.get("deadline")
    try:
        deadline = datetime.fromisoformat(str(deadline_raw)) if deadline_raw else None
    except ValueError:
        deadline = None
    if deadline is not None:
        deadline = _local(deadline)
    remaining = status.get("remaining_seconds")
    remaining_int = int(remaining) if isinstance(remaining, (int, float)) else None
    return deadline, remaining_int


def _live_line(target: legacy.MonitorTarget, started: datetime | None, status: dict[str, Any]) -> str:
    now = datetime.now().astimezone()
    deadline, remaining = _deadline_info(status)
    start_text = _clock(started)
    elapsed = int((now - started).total_seconds()) if started is not None else None
    elapsed_text = format_work_duration(max(0, elapsed)) if elapsed is not None else "unknown"
    if deadline is None:
        return f"▶ {target.summary} | start {start_text} | elapsed {elapsed_text} | planned end —"
    remaining_text = format_work_duration(max(0, remaining or 0))
    marker = "TIME UP" if remaining is not None and remaining <= 0 else f"remaining {remaining_text}"
    return (
        f"▶ {target.summary} | start {start_text} | end {_clock(deadline)} | "
        f"elapsed {elapsed_text} | {marker}"
    )


def _stdout_tty(app: Any) -> bool:
    stream = getattr(getattr(app, "io", None), "stdout", None)
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


def _live_update(app: Any, text: str, previous_width: int) -> int:
    stream = getattr(getattr(app, "io", None), "stdout", None)
    if _stdout_tty(app) and stream is not None and callable(getattr(stream, "write", None)):
        padded = text.ljust(previous_width)
        stream.write("\r" + padded)
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()
        return max(previous_width, len(text))
    if previous_width == 0:
        _show(app, text)
    return max(previous_width, len(text))


def _clear_live(app: Any, previous_width: int) -> None:
    if not previous_width or not _stdout_tty(app):
        return
    stream = getattr(getattr(app, "io", None), "stdout", None)
    if stream is not None and callable(getattr(stream, "write", None)):
        stream.write("\r" + (" " * previous_width) + "\r")
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()


def _poll_wait_input(app: Any) -> str | None:
    """Poll without stopping countdown refresh.

    POSIX terminals/pipes accept a full command followed by Enter. Windows console
    accepts the displayed single-key controls and `c` opens the normal command line.
    """
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        if not msvcrt.kbhit():
            return None
        char = msvcrt.getwch()
        if char in {"\r", "\n"}:
            return ""
        return char

    stream = sys.stdin
    try:
        ready, _, _ = select.select([stream], [], [], 0)
    except (OSError, ValueError):
        return None
    if not ready:
        return None
    line = stream.readline()
    if line == "":
        return "q"
    return line.rstrip("\r\n")


def _wait_help(app: Any) -> None:
    _show(app, "Waiting Mode controls")
    _show(app, "  p  pause current Task")
    _show(app, "  d  complete current Task")
    _show(app, "  c  open the normal console")
    _show(app, "  q  leave this client; Task/background Assistant keep running")
    _show(app, "  ?  show these controls")
    if os.name != "nt":
        _show(app, "  You may also type any normal command and press Enter.")


def _wait_interrupt(app: Any, target: legacy.MonitorTarget) -> str:
    choose = getattr(app.ctx.ui, "choose", None)
    if not callable(choose):
        return "console"
    selected = choose(
        f"Current Task — {target.summary}",
        (
            "Continue waiting",
            "Pause current Task",
            "Complete current Task",
            "Open console",
            "Exit client (Task keeps running)",
        ),
    )
    if selected is None or selected == "Continue waiting":
        return "wait"
    if selected == "Pause current Task":
        _execute_user(app, base.ParsedCommand(raw="pause", name="pause", args=()), paginate=False)
        return "console"
    if selected == "Complete current Task":
        _execute_user(app, base.ParsedCommand(raw="done", name="done", args=()), paginate=False)
        return "console"
    if selected == "Open console":
        return "console"
    return "exit"


def _waiting_mode(app: Any) -> str:
    target = legacy._monitor_target(app)
    if target is None or target.kind != "task" or not target.current_work:
        return "console"

    _show(app, "")
    _show(app, "Waiting Mode")
    _show(app, f"Task: {target.summary}")
    _show(app, "The background Assistant owns reminders; closing this terminal does not cancel the work period.")
    _wait_help(app)
    _show(app, "")

    started = _actual_work_start(app, target.value)
    try:
        cursor = legacy._cursor(app)
    except Exception:
        cursor = 0
    previous_width = 0
    next_refresh = 0.0
    last_period_state: str | None = None

    while True:
        try:
            now_mono = monotonic()
            if now_mono >= next_refresh:
                status = _work_period_status(app, target)
                state = str(status.get("state") or "none")
                if state == "error" and state != last_period_state:
                    _clear_live(app, previous_width)
                    previous_width = 0
                    _show(app, f"Work-period status unavailable: {status.get('error')}")
                    _show(app, "The Task itself is still governed by CalDAV/Session state.")
                previous_width = _live_update(app, _live_line(target, started, status), previous_width)
                if state == "expired" and last_period_state != "expired":
                    _clear_live(app, previous_width)
                    previous_width = 0
                    _show(app, "🔔 Planned work time has ended. The Task is still in progress.")
                    _show(app, "Choose d to complete, p to pause, or c to decide in the console.")
                last_period_state = state
                next_refresh = now_mono + 1.0

            try:
                events = legacy._events(app, cursor)
            except Exception:
                events = []
            for event in events:
                cursor = max(cursor, int(event.get("seq", cursor) or cursor))
                _clear_live(app, previous_width)
                previous_width = 0
                legacy._show_delivery(app, event, target)

            line = _poll_wait_input(app)
            if line is not None:
                _clear_live(app, previous_width)
                previous_width = 0
                raw = str(line).strip()
                key = raw.casefold()
                if key in {"p", "pause"}:
                    _execute_user(app, base.ParsedCommand(raw="pause", name="pause", args=()), paginate=False)
                    return "console"
                if key in {"d", "done", "complete"}:
                    _execute_user(app, base.ParsedCommand(raw="done", name="done", args=()), paginate=False)
                    return "console"
                if key in {"c", "console"}:
                    return "console"
                if key in {"q", "quit", "exit"}:
                    _show(app, "Leaving the foreground client. Current Task and background Assistant keep running.")
                    return "exit"
                if key in {"?", "help"}:
                    _wait_help(app)
                elif raw:
                    try:
                        parsed = base.parse_command_line(raw)
                    except ValueError as exc:
                        base._error(app, f"Invalid input: {exc}")
                    else:
                        if parsed is not None:
                            _, should_exit = _execute_user(app, parsed)
                            if should_exit:
                                return "exit"
                            fresh = legacy._monitor_target(app)
                            if fresh is None or fresh.key != target.key:
                                return "console"

            current = getattr(app.ctx.session, "current_task", lambda: None)()
            current_id = str(getattr(current, "id", "") or "").strip() or None
            if current_id != target.object_id:
                _clear_live(app, previous_width)
                return "console"
            sleep(0.1)
        except KeyboardInterrupt:
            _clear_live(app, previous_width)
            previous_width = 0
            action = _wait_interrupt(app, target)
            if action != "wait":
                return action


def _console(app: Any, snapshot: StartupSnapshot | None) -> tuple[int, str]:
    _show(app, "")
    _show(app, "Console ready. Enter opens the guided menu; commands are optional shortcuts.")
    _show(app, "Type guide for the Guide Book, dev for Developing Docs, or help for command help.")
    last_code = 0
    first_menu_snapshot = snapshot

    while True:
        target = legacy._monitor_target(app)
        if target is not None and target.kind == "task" and target.current_work:
            prompt = f"[doing: {target.summary}] > "
        else:
            prompt = "> "
        try:
            line = app.io.read(prompt)
        except EOFError:
            _show(app, "")
            return last_code, "exit"
        except KeyboardInterrupt:
            _show(app, "")
            return last_code, "exit"

        try:
            parsed = base.parse_command_line(line)
        except ValueError as exc:
            base._error(app, f"Invalid input: {exc}")
            last_code = 2
            continue

        if parsed is None:
            action = _home_menu(app, first_menu_snapshot)
            first_menu_snapshot = None
            if action == "wait":
                return last_code, "wait"
            if action == "exit":
                return last_code, "exit"
            continue

        if parsed.name.casefold() == "start" and not parsed.args:
            action = _guided_start(app)
            if action == "wait":
                return 0, "wait"
            if action == "exit":
                return 0, "exit"
            continue

        code, should_exit = _execute_user(app, parsed, paginate=True)
        last_code = code
        if should_exit:
            return code, "exit"

        target = legacy._monitor_target(app)
        if code == 0 and target is not None and target.kind == "task" and target.current_work:
            status = _work_period_status(app, target)
            if status.get("state") in {"scheduled", "expired"}:
                return last_code, "wait"


def run_conversation_repl(app: Any) -> int:
    base._emit_repl_started(app)
    snapshot = _show_welcome(app)
    last_code = 0

    target = legacy._monitor_target(app)
    if target is not None and target.kind == "task" and target.current_work:
        status = _work_period_status(app, target)
        if status.get("state") in {"scheduled", "expired"}:
            _show(app, "")
            _show(app, "A timed work session is already active; restoring Waiting Mode.")
            action = "wait"
        else:
            action = "console"
    else:
        action = "console"

    while True:
        if action == "wait":
            action = _waiting_mode(app)
            if action == "exit":
                return last_code
        if action == "console":
            last_code, action = _console(app, snapshot)
            snapshot = None
            if action == "exit":
                return last_code


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if app is None:
        from ..bootstrap import build_cli_application

        app = build_cli_application()

    if argv:
        # Keep scripting/one-shot compatibility. The richer conversation is an
        # interactive client concern; Core commands and their public contracts stay unchanged.
        return legacy.run_cli(argv, app=app)

    legacy._prepare(app, ())
    _register_conversation_commands(app)
    with completion_session(app):
        return run_conversation_repl(app)


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "StartupSnapshot",
    "run_conversation_repl",
    "run_cli",
    "main",
]
