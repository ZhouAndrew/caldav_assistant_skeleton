"""Human-friendly labels for Task selection menus.

This module is internal presentation logic.  It never changes Task identity or
business state: CalDAV UID remains the identity used by Core; labels only help a
human distinguish legitimate same-named Tasks.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any, Callable, Iterable


def _uid(task: Any) -> str:
    return str(getattr(task, "id", "") or "").strip()


def _summary(task: Any) -> str:
    value = str(getattr(task, "summary", "") or "").strip()
    return value or _uid(task) or "Task"


def _format_when(value: Any) -> str:
    if isinstance(value, datetime):
        # Presentation must not silently reinterpret a CalDAV timestamp in the
        # machine's current timezone.  Preserve the wall-clock/date carried by the
        # domain object; timezone normalization belongs to the temporal/domain layer.
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_categories(values: Any) -> str | None:
    if not isinstance(values, (list, tuple, set)):
        return None
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return None
    if len(cleaned) <= 2:
        return ", ".join(cleaned)
    return f"{cleaned[0]}, {cleaned[1]} +{len(cleaned) - 2}"


def deduplicate_tasks(items: Iterable[Any]) -> list[Any]:
    """Remove duplicate rows with the same non-empty CalDAV UID, preserving order."""
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        uid = _uid(item)
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
        result.append(item)
    return result


def _unique_uid_prefixes(items: list[Any], *, minimum: int = 4) -> dict[str, str]:
    uids = [_uid(item) for item in items if _uid(item)]
    result: dict[str, str] = {}
    for uid in uids:
        width = min(minimum, len(uid))
        while width < len(uid):
            prefix = uid[:width]
            if not any(other != uid and other.startswith(prefix) for other in uids):
                break
            width += 1
        result[uid] = uid[:width]
    return result


def task_labeler(items: Iterable[Any]) -> tuple[list[Any], Callable[[Any], str]]:
    """Return de-duplicated Tasks plus a label callback for a Menu.

    Unique summaries stay compact.  Same-named Tasks gain useful scheduling/context
    fields plus a shortest-unique UID prefix, guaranteeing that legitimate duplicate
    names remain distinguishable without dumping a full UID into normal UI.
    """
    tasks = deduplicate_tasks(items)
    summary_counts = Counter(_summary(task).casefold() for task in tasks)
    prefixes = _unique_uid_prefixes(tasks)
    labels: dict[int, str] = {}
    duplicate_ordinals: Counter[str] = Counter()

    for task in tasks:
        summary = _summary(task)
        key = summary.casefold()
        duplicate = summary_counts[key] > 1
        parts = [summary]

        due = getattr(task, "due", None)
        start = getattr(task, "start", None)
        if due is not None:
            parts.append(f"due {_format_when(due)}")
        elif start is not None:
            parts.append(f"start {_format_when(start)}")

        if duplicate:
            categories = _format_categories(getattr(task, "categories", None))
            if categories:
                parts.append(categories)

            uid = _uid(task)
            if uid:
                parts.append(f"#{prefixes[uid]}")
            else:
                duplicate_ordinals[key] += 1
                parts.append(f"item {duplicate_ordinals[key]}")

        labels[id(task)] = " · ".join(parts)

    def label(item: Any) -> str:
        return labels.get(id(item), _summary(item))

    return tasks, label


__all__ = ["deduplicate_tasks", "task_labeler"]
