"""Live-progress composition for the zero-learning conversation client.

`conversation_app` owns the welcome/guided-menu/Waiting-Mode experience.  This module
changes only foreground execution observability: lifecycle commands stream factual
Core milestones while they are happening.  It does not duplicate Task business
logic and it does not predict a call chain.
"""
from __future__ import annotations

from datetime import datetime
from time import monotonic
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


def _execute_user(
    app: Any,
    parsed: base.ParsedCommand,
    *,
    paginate: bool = True,
) -> tuple[int, bool]:
    """Execute one command and show each factual Core milestone immediately."""
    original = parsed
    effective, period_seconds = legacy._split_lifecycle_duration(parsed)
    conversation._show(app, "")
    conversation._show(app, f"Working: {original.raw}")
    conversation._show(app, "Progress is reported by the operation that actually performs each step.")
    started = monotonic()

    delivery_target = legacy._monitor_target(app)

    def execute_core() -> tuple[int, bool]:
        return base._execute(app, effective, paginate=paginate)

    def on_delivery(event: dict[str, Any]) -> None:
        target = delivery_target or legacy._monitor_target(app)
        if target is not None:
            _delivery_only(app, event, target)

    code, should_exit = run_with_live_progress(
        app,
        execute_core,
        on_progress=lambda event: _show_progress(app, event),
        on_delivery=on_delivery,
    )

    # Work-period allocation remains a distinct Assistant operation.  It already
    # reports before and after execution here, while Task DUE/DTSTART remain untouched.
    if code == 0 and period_seconds is not None:
        target = legacy._monitor_target(app)
        if target is None or target.kind != "task" or not target.current_work or not target.object_id:
            conversation._show(
                app,
                "✗ Task started, but the Assistant could not resolve the current Task for its work period.",
            )
            code = 1
        else:
            conversation._show(app, "→ Setting the work-period reminder in the background Assistant…")
            try:
                status = legacy._runtime_call(
                    app,
                    "work_period.allocate",
                    task_id=target.object_id,
                    seconds=period_seconds,
                )
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
                        f"  Remaining: {legacy.format_work_duration(max(0, int(remaining)))}",
                    )
                conversation._show(app, "  Task DUE/DTSTART were not changed.")

    elapsed = monotonic() - started
    if code == 0:
        conversation._show(app, f"✓ Operation finished ({elapsed:.1f}s)")
    else:
        conversation._show(app, f"✗ Operation did not fully succeed ({elapsed:.1f}s)")
    return code, should_exit


def _install() -> None:
    # Functions in conversation_app resolve module globals at call time. Replacing
    # this single presentation brick makes guided start, Waiting Mode, and console
    # commands share the same live runner without copying the whole conversation UI.
    conversation._execute_user = _execute_user
    legacy._show_delivery = _delivery_only


def run_cli(argv: Sequence[str] | None = None, *, app: Any = None) -> int:
    _install()
    return conversation.run_cli(argv, app=app)


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_cli", "main"]
