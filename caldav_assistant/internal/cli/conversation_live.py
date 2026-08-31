"""Live-progress composition for the zero-learning conversation client.

`conversation_app` owns the welcome/guided-menu experience. This module composes the
live foreground behavior used by the installed client:

- startup reads Upcoming + Recommended from one Core source traversal;
- lifecycle commands stream factual Core milestones plus truthful elapsed heartbeats;
- Waiting Mode stays on the main thread, computes its countdown locally from the
  authoritative background deadline, receives keyboard/Ctrl-C immediately, and only
  polls the background event feed at a modest cadence;
- the Background Assistant remains the owner of real reminder delivery, so closing
  the CLI never cancels a work period.

Task/Event business logic remains in Core services and the frozen Public API is not
changed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from time import monotonic, sleep
from typing import Any, Sequence

from . import app as base
from . import conversation_app as conversation
from . import monitor_app as legacy
from .live_command import run_with_live_progress


_original_show_delivery = legacy._show_delivery


def _delivery_only(app: Any, event: dict[str, Any], target: Any) -> None:
    """Never turn internal operation progress into a reminder/bell."""
    if event.get("kind") == "operation_progress":
        return
    _original_show_delivery(app, event, target)


def _show_progress(app: Any, event: dict[str, Any]) -> None:
    state = str(event.get("state") or "info")
    prefix = {"started": "→", "done": "✓", "failed": "!"}.get(state, "·")
    conversation._show(
        app,
        f"{prefix} {event.get('message') or event.get('stage') or 'Progress'}",
    )


def _read_snapshot(app: Any) -> conversation.StartupSnapshot:
    """Read startup state without traversing all Tasks/Events twice."""
    hours = conversation._window_hours(app)
    now = datetime.now().astimezone()
    end = now + timedelta(hours=hours)

    session = getattr(app.ctx, "session", None)
    current_getter = getattr(session, "current_task", None)
    current = current_getter() if callable(current_getter) else None

    days = max(1, int(math.ceil(hours / 24.0)) + 1)
    runtime = getattr(app, "runtime", None)
    runtime_call = getattr(runtime, "call", None)
    if callable(runtime_call):
        bundle = legacy._runtime_call(
            app,
            "agenda.startup_snapshot",
            days=days,
            kind="task",
        )
        if not isinstance(bundle, dict):
            raise RuntimeError("Invalid startup agenda response")
        agenda = bundle.get("agenda")
        recommendation = bundle.get("recommendation")
    else:
        # Deliberately small test contexts may have no Runtime connection.
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


def _show_welcome(app: Any) -> conversation.StartupSnapshot:
    """Render unavailable live data as unknown, never as an empty agenda."""
    conversation._show(app, "CalDAV Assistant")
    conversation._show(app, conversation._greeting())
    conversation._show(app, "")

    error: Exception | None = None
    try:
        snapshot = conversation._visible_call(
            app,
            "Reading current work, Tasks and Events…",
            lambda: _read_snapshot(app),
        )
    except Exception as exc:
        error = exc
        snapshot = conversation.StartupSnapshot(
            window_hours=conversation._window_hours(app),
            warning=f"Live agenda is unavailable: {type(exc).__name__}: {exc}",
        )

    conversation._show(app, "")
    conversation._show(app, "Now")
    if error is not None:
        conversation._show(app, "  Live current-work state is unavailable.")
    elif snapshot.current_task is None:
        conversation._show(app, "  No Task is currently being worked on.")
    else:
        conversation._show(app, f"  ▶ {conversation._summary(snapshot.current_task)}")

    conversation._show(app, "")
    if error is not None:
        conversation._show(app, f"Upcoming · next {snapshot.window_hours}h")
        conversation._show(app, "  Live Task/Event data is unavailable.")
    else:
        conversation._show(app, conversation._snapshot_text(snapshot))

    conversation._show(app, "")
    conversation._show(app, "Recommended")
    if error is not None:
        conversation._show(app, "  Live recommendation is unavailable.")
    elif snapshot.recommended is None:
        conversation._show(app, "  No actionable Task is recommended right now.")
    else:
        task = snapshot.recommended
        due = getattr(task, "due", None)
        detail = f" — due {conversation._short_when(due)}" if due is not None else ""
        conversation._show(app, f"  → {conversation._summary(task)}{detail}")

    if snapshot.warning:
        conversation._show(app, "")
        conversation._show(app, f"Warning: {snapshot.warning}")
        conversation._show(
            app,
            "The Assistant will not pretend that unavailable live data is empty or current.",
        )

    conversation._show(app, "")
    conversation._show(app, "Press Enter for the guided menu, or type a command directly.")
    conversation._show(app, "Guide Book: guide    Developing Docs: dev    Help: help")
    return snapshot


def _execute_user(
    app: Any,
    parsed: base.ParsedCommand,
    *,
    paginate: bool = True,
) -> tuple[int, bool]:
    """Execute one command with factual milestones and truthful liveness."""
    original = parsed
    effective, period_seconds = legacy._split_lifecycle_duration(parsed)
    conversation._show(app, "")
    conversation._show(app, f"Working: {original.raw}")
    conversation._show(
        app,
        "Progress is reported by the operation that actually performs each step.",
    )
    started = monotonic()

    delivery_target = legacy._monitor_target(app)

    def execute_core() -> base.CommandOutcome:
        return base.execute_command(app, effective)

    def on_delivery(event: dict[str, Any]) -> None:
        target = delivery_target or legacy._monitor_target(app)
        if target is not None:
            _delivery_only(app, event, target)

    def on_interrupt() -> None:
        conversation._show(app, "")
        conversation._show(
            app,
            "Interrupt received. The operation is already in progress; waiting for its authoritative result.",
        )
        conversation._show(
            app,
            "The Assistant will not claim a CalDAV write was cancelled unless Core confirms it.",
        )

    outcome = run_with_live_progress(
        app,
        execute_core,
        on_progress=lambda event: _show_progress(app, event),
        on_delivery=on_delivery,
        on_heartbeat=lambda elapsed: conversation._show(
            app, f"  Still working… {int(elapsed)}s elapsed"
        ),
        on_interrupt=on_interrupt,
    )
    code = outcome.exit_code
    should_exit = outcome.should_exit
    result = outcome.result

    # Every service-side milestone emitted before the IPC result has been drained.
    # Only now may the final result/What-changed presentation be shown.
    if result is not None:
        base._render_result(app, result, paginate=paginate)

    # Work-period allocation is a distinct Assistant operation. Anchor its deadline
    # to the Activity Journal's actual Task start/resume, not to the much later time
    # when a slow lifecycle command happens to return to the CLI.
    if code == 0 and period_seconds is not None:
        target = legacy._monitor_target(app)
        if (
            target is None
            or target.kind != "task"
            or not target.current_work
            or not target.object_id
        ):
            conversation._show(
                app,
                "✗ Task started, but the Assistant could not resolve the current Task for its work period.",
            )
            code = 1
        else:
            conversation._show(
                app,
                "→ Setting the work-period reminder in the background Assistant…",
            )
            payload: dict[str, Any] = {
                "task_id": target.object_id,
                "seconds": period_seconds,
            }
            actual_started = conversation._actual_work_start(app, target.value)
            if actual_started is not None:
                payload["started_at"] = actual_started.isoformat()
            try:
                status = legacy._runtime_call(app, "work_period.allocate", **payload)
            except Exception as exc:
                conversation._show(
                    app,
                    f"✗ Task lifecycle succeeded, but work-period setup failed: {type(exc).__name__}: {exc}",
                )
                code = 1
            else:
                deadline = status.get("deadline") if isinstance(status, dict) else None
                remaining = status.get("remaining_seconds") if isinstance(status, dict) else None
                conversation._show(app, "✓ Work period is active.")
                if deadline:
                    try:
                        planned = datetime.fromisoformat(str(deadline))
                    except ValueError:
                        planned_text = str(deadline)
                    else:
                        planned_text = conversation._clock(planned)
                else:
                    planned_text = "unknown"
                conversation._show(app, f"  Planned end: {planned_text}")
                if isinstance(remaining, (int, float)):
                    conversation._show(
                        app,
                        f"  Remaining: {conversation.format_work_duration(max(0, int(remaining)))}",
                    )
                conversation._show(app, "  Task DUE/DTSTART were not changed.")

    elapsed = monotonic() - started
    if code == 0:
        conversation._show(app, f"✓ Operation finished ({elapsed:.1f}s)")
    else:
        conversation._show(app, f"✗ Operation did not fully succeed ({elapsed:.1f}s)")
    return code, should_exit


def _started_from_status(status: dict[str, Any]) -> datetime | None:
    raw = status.get("started_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return conversation._local(value)


def _local_period_status(
    seed: dict[str, Any],
    deadline: datetime | None,
) -> dict[str, Any]:
    """Advance display-only remaining time without another IPC status request."""
    value = dict(seed)
    if deadline is None:
        return value
    remaining = int((deadline - datetime.now().astimezone()).total_seconds())
    value["remaining_seconds"] = remaining
    value["state"] = "scheduled" if remaining > 0 else "expired"
    return value


def _waiting_mode(app: Any) -> str:
    """Main-thread Waiting Mode: countdown, keyboard, Ctrl-C and delivery feed."""
    target = legacy._monitor_target(app)
    if target is None or target.kind != "task" or not target.current_work:
        return "console"

    conversation._show(app, "")
    conversation._show(app, "Waiting Mode")
    conversation._show(app, f"Task: {target.summary}")
    conversation._show(
        app,
        "The background Assistant owns reminders; closing this terminal does not cancel the work period.",
    )
    conversation._wait_help(app)
    conversation._show(app, "")

    # One authoritative status read establishes the deadline. Remaining time is a
    # pure local clock calculation after this point; the CLI does not ask the
    # background service for the same countdown every second.
    seed_status = conversation._work_period_status(app, target)
    deadline, _ = conversation._deadline_info(seed_status)
    started = _started_from_status(seed_status)
    if started is None:
        started = conversation._actual_work_start(app, target.value)

    try:
        cursor = legacy._cursor(app)
    except Exception:
        cursor = 0

    previous_width = 0
    next_refresh = 0.0
    next_event_poll = 0.0
    next_current_check = 0.0
    last_period_state: str | None = None

    while True:
        try:
            now_mono = monotonic()

            if now_mono >= next_refresh:
                status = _local_period_status(seed_status, deadline)
                state = str(status.get("state") or "none")
                if state == "error" and state != last_period_state:
                    conversation._clear_live(app, previous_width)
                    previous_width = 0
                    conversation._show(
                        app, f"Work-period status unavailable: {status.get('error')}"
                    )
                    conversation._show(
                        app,
                        "The Task itself is still governed by CalDAV/Session state.",
                    )
                previous_width = conversation._live_update(
                    app,
                    conversation._live_line(target, started, status),
                    previous_width,
                )
                if state == "expired" and last_period_state != "expired":
                    conversation._clear_live(app, previous_width)
                    previous_width = 0
                    conversation._show(
                        app,
                        "🔔 Planned work time has ended. The Task is still in progress.",
                    )
                    conversation._show(
                        app,
                        "Choose d to complete, p to pause, or c to decide in the console.",
                    )
                last_period_state = state
                next_refresh = now_mono + 1.0

            # Real notification delivery remains a Background Assistant concern.
            # Poll its bounded event feed at 2 Hz, not the former 10-20 Hz loops.
            if now_mono >= next_event_poll:
                try:
                    events = legacy._events(app, cursor)
                except Exception:
                    events = []
                for event in events:
                    cursor = max(cursor, int(event.get("seq", cursor) or cursor))
                    conversation._clear_live(app, previous_width)
                    previous_width = 0
                    _delivery_only(app, event, target)
                next_event_poll = now_mono + 0.5

            line = conversation._poll_wait_input(app)
            if line is not None:
                conversation._clear_live(app, previous_width)
                previous_width = 0
                raw = str(line).strip()
                key = raw.casefold()
                if key in {"p", "pause"}:
                    _execute_user(
                        app,
                        base.ParsedCommand(raw="pause", name="pause", args=()),
                        paginate=False,
                    )
                    return "console"
                if key in {"d", "done", "complete"}:
                    _execute_user(
                        app,
                        base.ParsedCommand(raw="done", name="done", args=()),
                        paginate=False,
                    )
                    return "console"
                if key in {"c", "console"}:
                    return "console"
                if key in {"q", "quit", "exit"}:
                    conversation._show(
                        app,
                        "Leaving the foreground client. Current Task and background Assistant keep running.",
                    )
                    return "exit"
                if key in {"?", "help"}:
                    conversation._wait_help(app)
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

            # Another client may pause/complete the Task. Recheck occasionally,
            # rather than issuing a Session IPC request ten times per second.
            if now_mono >= next_current_check:
                current = getattr(app.ctx.session, "current_task", lambda: None)()
                current_id = str(getattr(current, "id", "") or "").strip() or None
                if current_id != target.object_id:
                    conversation._clear_live(app, previous_width)
                    return "console"
                next_current_check = now_mono + 2.0

            sleep(0.05)
        except KeyboardInterrupt:
            conversation._clear_live(app, previous_width)
            previous_width = 0
            action = conversation._wait_interrupt(app, target)
            if action != "wait":
                return action
            # Repaint immediately after the interrupt menu.
            next_refresh = 0.0


def _install() -> None:
    # Functions in conversation_app resolve module globals at call time. Replacing
    # these presentation/composition bricks keeps Core logic singular while the
    # installed client gets the real-use behavior above.
    conversation._read_snapshot = _read_snapshot
    conversation._show_welcome = _show_welcome
    conversation._execute_user = _execute_user
    conversation._waiting_mode = _waiting_mode
    legacy._show_delivery = _delivery_only


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    _install()
    return conversation.run_cli(argv, app=app)


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_cli", "main"]
