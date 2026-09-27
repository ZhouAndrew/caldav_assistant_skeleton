"""Shared Task state semantics used by Core and presentation adapters.

These helpers are intentionally small and side-effect free.  They describe whether
an authoritative CalDAV Task can still participate in a human work flow; they do
not read Assistant session state and do not mutate the Task.
"""
from __future__ import annotations

from typing import Any


_FINISHED_STATUSES = frozenset({"COMPLETED", "CANCELLED"})


def task_is_finished(task: Any) -> bool:
    """Return True when a Task is completed or cancelled."""
    if bool(getattr(task, "completed", False)):
        return True
    status = str(getattr(task, "status", "") or "").strip().upper()
    return status in _FINISHED_STATUSES


def task_is_actionable(task: Any) -> bool:
    """Return True when a Task may still be selected for active work."""
    return not task_is_finished(task)


__all__ = ["task_is_finished", "task_is_actionable"]
