"""Human-facing command semantics and operation explanations.

This module is presentation-only. Core services remain authoritative for mutations;
this layer explains those mutations in vocabulary a user can verify. It must not
write CalDAV, Activity, WordPress, or local state itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_WORKLOG_KEY = "caldav.worklog_collection_url"


@dataclass(frozen=True, slots=True)
class CommandSemantics:
    usage: str
    meaning: str
    requires: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    does_not: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    verify: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


def _task_name(task: Any) -> str:
    summary = str(getattr(task, "summary", "") or "").strip()
    if summary:
        return summary
    task_id = str(getattr(task, "id", "") or "").strip()
    return task_id or "Task"


def _worklog_destination(ctx: Any) -> str | None:
    settings = getattr(ctx, "settings", None)
    getter = getattr(settings, "get", None)
    if not callable(getter):
        return None
    try:
        value = getter(_WORKLOG_KEY, None)
    except Exception:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _activity_stamp(ctx: Any, task: Any, action: str) -> Any:
    activity = getattr(ctx, "activity", None)
    reader = getattr(activity, "for_task", None)
    if not callable(reader):
        return None
    try:
        matches = [
            item
            for item in (reader(task) or ())
            if str(getattr(item, "action", "") or "") == action
        ]
    except Exception:
        return None
    if not matches:
        return None
    latest = max(matches, key=lambda item: getattr(item, "timestamp", 0))
    return getattr(latest, "timestamp", None)


def attach_result_explanation(result: Any, text: str) -> Any:
    """Attach CLI explanation without changing the frozen ActionResult shape."""
    if result is None:
        return None
    if hasattr(result, "message"):
        try:
            result.message = text
        except Exception:
            pass
    return result


def lifecycle_explanation(
    ctx: Any,
    action: str,
    task: Any,
    result: Any,
    *,
    was_current: bool | None = None,
) -> str:
    """Explain successful Task lifecycle mutations and their storage destinations."""
    name = _task_name(task)
    affected = getattr(result, "affected", None) or task
    worklog = _worklog_destination(ctx)
    action_map = {
        "start": ("Started work", "task_started", "task.started"),
        "pause": ("Paused work", "task_paused", "task.paused"),
        "resume": ("Resumed work", "task_resumed", "task.resumed"),
        "done": ("Completed task", "task_completed", None),
    }
    title, activity_action, hook = action_map[action]
    stamp = _activity_stamp(ctx, affected, activity_action)
    lines = [f"{title}: {name}", "", "What changed:"]

    if action == "start":
        lines.append("  CalDAV VTODO: STATUS -> IN-PROCESS (this is actual work state, not planned DTSTART).")
        if worklog:
            lines.append(f"  CalDAV Work VEVENT: opened a work interval in {worklog}.")
        else:
            lines.append("  Work session: no Work Log destination was visible to this CLI; Activity Journal is the fallback record.")
    elif action == "pause":
        lines.append("  CalDAV VTODO: remains STATUS:IN-PROCESS; pause does not complete or reschedule the Task.")
        if worklog:
            lines.append(f"  CalDAV Work VEVENT: closed the current interval (DTEND set, open marker removed) in {worklog}.")
        else:
            lines.append("  Work session: paused state is derived from the Activity Journal fallback because no Work Log destination was visible.")
    elif action == "resume":
        lines.append("  CalDAV VTODO: remains STATUS:IN-PROCESS; planned DTSTART is unchanged.")
        if worklog:
            lines.append(f"  CalDAV Work VEVENT: opened a new work interval in {worklog}.")
        else:
            lines.append("  Work session: resumed state is derived from the Activity Journal fallback because no Work Log destination was visible.")
    elif action == "done":
        completed_at = getattr(affected, "completed_at", None)
        lines.append("  CalDAV VTODO: STATUS -> COMPLETED; completed=true; standard completion fields are persisted by the CalDAV adapter.")
        if completed_at is not None:
            lines.append(f"  Completion time: {completed_at}.")
        if was_current and worklog:
            lines.append(f"  CalDAV Work VEVENT: closed the current work interval in {worklog}.")
        elif was_current:
            lines.append("  Work session: the current interval ended; Activity Journal is the available work-history fallback.")
        else:
            lines.append("  Work session: this Task was not the current active work, so no current interval needed to be closed.")

    if stamp is not None:
        lines.append(f"  Activity Journal (SQLite): {activity_action} recorded at {stamp}.")
    else:
        lines.append(f"  Activity Journal: {activity_action} is the lifecycle audit record for this operation.")

    if hook:
        lines.extend(
            [
                "",
                "Secondary effects:",
                f"  Hook: {hook} emitted after the Activity record; extension failures cannot roll back the Task action.",
                "  WordPress: the bundled work-session logging extension may enqueue a long-term log when enabled.",
                "  Verify delivery with: history pending / history wordpress",
            ]
        )
    elif action == "done":
        lines.extend(
            [
                "",
                "Secondary effects:",
                "  Completion logging is separate from the authoritative CalDAV completion and may use the WordPress Outbox.",
                "  Verify delivery with: history pending / history wordpress",
            ]
        )

    undo = bool(getattr(result, "undo_available", False))
    lines.extend(["", f"Undo: {'available' if undo else 'not available for this operation'}."])
    return "\n".join(lines)


def log_explanation(text: str, result: Any) -> str:
    message = str(getattr(result, "message", "") or "").strip()
    lines = ["Long-term log accepted.", "", "What happened:"]
    lines.append("  WordPressService: the log request is persisted through the durable Outbox before/while delivery is attempted.")
    lines.append("  Task/Event state: unchanged.")
    if message:
        lines.append(f"  Delivery status: {message}")
    lines.extend(
        [
            "",
            "Verify:",
            "  history pending     - requests still waiting in the Outbox",
            "  history wordpress   - content that really exists in today's WordPress post",
        ]
    )
    return "\n".join(lines)


_SEMANTICS: dict[str, CommandSemantics] = {
    "start": CommandSemantics(
        usage="start [task name | list number]",
        meaning="Begin actually working on a Task now. This is not an edit of the Task's planned DTSTART.",
        requires=("No other Task may currently be active.", "The Task must not be completed or cancelled."),
        writes=(
            "CalDAV VTODO: sets the Task to STATUS:IN-PROCESS.",
            "CalDAV Work VEVENT: opens an actual-work interval when a Work Log collection is configured.",
            "Activity Journal (SQLite): records task_started.",
        ),
        does_not=("Does not rewrite the planned start time (DTSTART).",),
        side_effects=("Emits task.started; enabled extensions may enqueue secondary logs such as WordPress work-session entries.",),
        verify=("current", "history task <task>", "history pending", "history wordpress"),
        examples=("start", "start Anki", "start 1"),
    ),
    "pause": CommandSemantics(
        usage="pause",
        meaning="Pause the Task you are actually working on now. It does not accept an arbitrary planned Task name.",
        requires=("There must be one current Task started/resumed by the Assistant.",),
        writes=(
            "CalDAV Work VEVENT: closes the open actual-work interval (DTEND set; open marker removed) when Work Log is configured.",
            "Activity Journal (SQLite): records task_paused.",
        ),
        does_not=(
            "Does not complete the Task.",
            "Does not change planned DTSTART or due date.",
            "The VTODO remains STATUS:IN-PROCESS while the work session is paused.",
        ),
        side_effects=("Emits task.paused; enabled extensions may enqueue a WordPress/Outbox work-session log.",),
        verify=("current", "resume", "history task <task>", "history pending", "history wordpress"),
        examples=("pause",),
    ),
    "resume": CommandSemantics(
        usage="resume",
        meaning="Continue work that this Assistant previously paused.",
        requires=("No other Task may currently be active.", "At least one previously paused Task must exist."),
        writes=(
            "CalDAV Work VEVENT: opens a new actual-work interval when Work Log is configured.",
            "Activity Journal (SQLite): records task_resumed.",
        ),
        does_not=("Does not rewrite planned DTSTART; the VTODO remains STATUS:IN-PROCESS.",),
        side_effects=("Emits task.resumed; enabled extensions may enqueue a WordPress/Outbox work-session log.",),
        verify=("current", "history task <task>", "history pending", "history wordpress"),
        examples=("resume",),
    ),
    "done": CommandSemantics(
        usage="done [task name | list number]",
        meaning="Mark a Task authoritatively complete. Alias: complete.",
        writes=(
            "CalDAV VTODO: STATUS=COMPLETED, completed=true, completion timestamp, and standard completion fields through the adapter.",
            "CalDAV Work VEVENT: closes the current work interval if this Task is active and Work Log is configured.",
            "Activity Journal (SQLite): records task_completed.",
        ),
        does_not=("WordPress success is not required for Task completion to succeed.",),
        side_effects=("Completion logging may enqueue a human-readable summary through the WordPress Outbox.",),
        verify=("history task <task>", "history pending", "history wordpress", "undo"),
        examples=("done", "done Report", "complete 1"),
    ),
    "current": CommandSemantics(
        usage="current",
        meaning="Show the Task the Assistant can prove you are working on now; alias: now.",
        writes=(),
        does_not=("Does not infer 'current' from planned DTSTART alone.",),
        side_effects=("With Work Log configured, open CalDAV Work VEVENTs are the cross-device source; otherwise Activity lifecycle records are the local fallback.",),
        verify=("history task <task>",),
        examples=("current", "now"),
    ),
    "edit": CommandSemantics(
        usage="edit [task name | list number]",
        meaning="Edit planned Task facts such as title, due date, or priority.",
        writes=("CalDAV VTODO fields selected by the user.", "Activity Journal records the successful planning change."),
        does_not=("Does not mean start/pause/resume actual work.",),
        verify=("history task <task>", "undo"),
        examples=("edit", "edit Anki", "edit 1"),
    ),
    "next": CommandSemantics(
        usage="next",
        meaning="Ask the Agenda/Next engine for the recommended next item; this is a recommendation, not simply 'earliest due date'.",
        writes=(),
        examples=("next",),
    ),
    "today": CommandSemantics(
        usage="today",
        meaning="Show today's relevant Tasks and Events without changing them.",
        writes=(),
        examples=("today",),
    ),
    "log": CommandSemantics(
        usage="log [text]",
        meaning="Write a human long-term note through the WordPress logging path.",
        writes=("WordPress Outbox: durable request used for reliable delivery.", "WordPress daily post: updated/created when delivery succeeds."),
        does_not=("Does not change Task or Event state.",),
        verify=("history pending", "history wordpress"),
        examples=("log Finished chapter 3", "log"),
    ),
    "history": CommandSemantics(
        usage="history [today | task [name] | wordpress | pending]",
        meaning="Inspect what really happened at each storage layer instead of treating every kind of log as the same thing.",
        writes=(),
        side_effects=(
            "history today/task reads the local Activity Journal.",
            "history wordpress reads real WordPress post content.",
            "history pending reads the durable WordPress Outbox.",
        ),
        examples=("history today", "history task Anki", "history wordpress", "history pending"),
    ),
    "help": CommandSemantics(
        usage="help [command]",
        meaning="List commands or explain one command's human meaning, requirements, writes, non-effects, side effects, and verification paths.",
        writes=(),
        examples=("help", "help pause", "help done"),
    ),
    "background": CommandSemantics(
        usage="background [status | start | stop | restart | enable | disable]",
        meaning="Inspect or manage the lightweight Assistant background service used for reminders, maintenance, IPC, and reliable delivery.",
        verify=("background status",),
    ),
    "settings": CommandSemantics(
        usage="settings [category/action]",
        meaning="Inspect or change validated Assistant configuration without editing configuration files by hand.",
        verify=("settings", "settings caldav status"),
    ),
    "extensions": CommandSemantics(
        usage="extensions",
        meaning="List installed Assistant extensions and their state.",
        writes=(),
        verify=("extension errors",),
    ),
    "extension": CommandSemantics(
        usage="extension <add|load|enable|disable|reload|unload|errors> ...",
        meaning="Manage an extension lifecycle without modifying Core source files.",
        verify=("extensions", "extension errors"),
    ),
    "menu": CommandSemantics(
        usage="menu",
        meaning="Open optional multi-level navigation. Menu items dispatch to the same canonical commands; this is not a second business-logic implementation.",
        writes=(),
        examples=("menu", "m"),
    ),
    "undo": CommandSemantics(
        usage="undo",
        meaning="Undo the most recent supported mutation recorded by UndoManager.",
        writes=("Reapplies the stored previous authoritative state for supported operations.",),
    ),
}


def format_command_help(entry: Any) -> str:
    name = str(getattr(entry, "name", "") or "").strip()
    description = str(getattr(entry, "description", "") or "").strip() or "No description."
    aliases = ", ".join(getattr(entry, "aliases", ()) or ()) or "-"
    source = str(getattr(entry, "source", "") or "-")
    spec = _SEMANTICS.get(name)
    if spec is None:
        return f"{name}\n  {description}\n  aliases: {aliases}\n  source: {source}"

    lines = [name, f"  {description}", "", f"Usage: {spec.usage}", f"Meaning: {spec.meaning}"]
    sections = (
        ("Requires", spec.requires),
        ("Writes / changes", spec.writes),
        ("Does not", spec.does_not),
        ("Secondary effects / data source", spec.side_effects),
        ("Verify with", spec.verify),
        ("Examples", spec.examples),
    )
    for title, items in sections:
        if not items:
            continue
        lines.extend(["", f"{title}:"])
        lines.extend(f"  - {item}" for item in items)
    lines.extend(["", f"aliases: {aliases}", f"source: {source}"])
    return "\n".join(lines)


def help_list_footer() -> tuple[str, ...]:
    return (
        "",
        "Use 'help <command>' for meaning, data writes, side effects, and verification.",
        "Use 'history' to inspect Activity, real WordPress content, or pending Outbox items.",
    )


__all__ = [
    "CommandSemantics",
    "attach_result_explanation",
    "format_command_help",
    "help_list_footer",
    "lifecycle_explanation",
    "log_explanation",
]
