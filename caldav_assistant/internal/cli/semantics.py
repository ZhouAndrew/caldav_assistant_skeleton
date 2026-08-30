"""Human-facing command semantics and operation explanations.

This module is presentation-only. Core services remain authoritative for mutations;
this layer explains those mutations in vocabulary a user can verify. It must not
write CalDAV, Activity, WordPress, or local state itself.

The command help contract deliberately includes a developer-facing runtime path. A
help entry is not useful if it only repeats the label; it must say which composition
brick/service/adapter is involved, what persistent state changes, and how to verify
that result independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_WORKLOG_KEY = "caldav.worklog_collection_url"


@dataclass(frozen=True, slots=True)
class CommandSemantics:
    usage: str
    meaning: str
    path: tuple[str, ...] = ()
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
        lines.append(
            "  CalDAV VTODO: STATUS -> IN-PROCESS "
            "(this is actual work state, not planned DTSTART)."
        )
        if worklog:
            lines.append(f"  CalDAV Work VEVENT: opened a work interval in {worklog}.")
        else:
            lines.append(
                "  Work session: no Work Log destination was visible to this CLI; "
                "Activity Journal is the fallback record."
            )
    elif action == "pause":
        lines.append(
            "  CalDAV VTODO: remains STATUS:IN-PROCESS; pause does not complete or "
            "reschedule the Task."
        )
        if worklog:
            lines.append(
                "  CalDAV Work VEVENT: closed the current interval "
                f"(DTEND set, open marker removed) in {worklog}."
            )
        else:
            lines.append(
                "  Work session: paused state is derived from the Activity Journal "
                "fallback because no Work Log destination was visible."
            )
    elif action == "resume":
        lines.append(
            "  CalDAV VTODO: remains STATUS:IN-PROCESS; planned DTSTART is unchanged."
        )
        if worklog:
            lines.append(f"  CalDAV Work VEVENT: opened a new work interval in {worklog}.")
        else:
            lines.append(
                "  Work session: resumed state is derived from the Activity Journal "
                "fallback because no Work Log destination was visible."
            )
    elif action == "done":
        completed_at = getattr(affected, "completed_at", None)
        lines.append(
            "  CalDAV VTODO: STATUS -> COMPLETED; completed=true; standard completion "
            "fields are persisted by the CalDAV adapter."
        )
        if completed_at is not None:
            lines.append(f"  Completion time: {completed_at}.")
        if was_current and worklog:
            lines.append(
                f"  CalDAV Work VEVENT: closed the current work interval in {worklog}."
            )
        elif was_current:
            lines.append(
                "  Work session: the current interval ended; Activity Journal is the "
                "available work-history fallback."
            )
        else:
            lines.append(
                "  Work session: this Task was not the current active work, so no "
                "current interval needed to be closed."
            )

    if stamp is not None:
        lines.append(
            f"  Activity Journal (SQLite): {activity_action} recorded at {stamp}."
        )
    else:
        lines.append(
            f"  Activity Journal: {activity_action} is the lifecycle audit record for "
            "this operation."
        )

    if hook:
        lines.extend(
            [
                "",
                "Secondary effects:",
                f"  Hook: {hook} emitted after the Activity record; extension failures "
                "cannot roll back the Task action.",
                "  WordPress: the bundled work-session logging extension may enqueue "
                "a long-term log when enabled.",
                "  Verify delivery with: history pending / history wordpress",
            ]
        )
    elif action == "done":
        lines.extend(
            [
                "",
                "Secondary effects:",
                "  Completion logging is separate from the authoritative CalDAV "
                "completion and may use the WordPress Outbox.",
                "  Verify delivery with: history pending / history wordpress",
            ]
        )

    undo = bool(getattr(result, "undo_available", False))
    lines.extend(
        ["", f"Undo: {'available' if undo else 'not available for this operation'}." ]
    )
    return "\n".join(lines)


def log_explanation(text: str, result: Any) -> str:
    message = str(getattr(result, "message", "") or "").strip()
    lines = ["Long-term log accepted.", "", "What happened:"]
    lines.append(
        "  WordPressService: the log request is persisted through the durable Outbox "
        "before/while delivery is attempted."
    )
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
    "today": CommandSemantics(
        usage="today",
        meaning="Show today's relevant Tasks and Events without changing them.",
        path=(
            "CLI/Menu -> CommandService -> ctx.agenda.today()",
            "AgendaService/AgendaEngine -> Task/Event read path -> presenter",
        ),
        writes=(),
        verify=("Run today again.", "settings cache status (to inspect cache vs CalDAV reads)."),
        examples=("today",),
    ),
    "next": CommandSemantics(
        usage="next",
        meaning=(
            "Ask the Agenda/Next engine for the recommended next item; this is a "
            "recommendation, not simply 'earliest due date'."
        ),
        path=(
            "CLI/Menu -> CommandService -> ctx.agenda.next()",
            "AgendaService -> NextEngine -> Task/Event read path -> presenter",
        ),
        writes=(),
        does_not=("Does not automatically start or modify the recommended Task.",),
        verify=("today", "current"),
        examples=("next",),
    ),
    "current": CommandSemantics(
        usage="current",
        meaning=(
            "Show the Task the Assistant can prove you are working on now; alias: now."
        ),
        path=(
            "CLI -> CommandService -> Session current-task lookup",
            "Work Log/Activity lifecycle context -> Task presenter",
        ),
        writes=(),
        does_not=("Does not infer 'current' from planned DTSTART alone.",),
        side_effects=(
            "With Work Log configured, open CalDAV Work VEVENTs are the cross-device "
            "source; otherwise Activity lifecycle records are the local fallback.",
        ),
        verify=("history task <task>",),
        examples=("current", "now"),
    ),
    "start": CommandSemantics(
        usage="start [task name | list number]",
        meaning=(
            "Begin actually working on a Task now. This is not an edit of the Task's "
            "planned DTSTART."
        ),
        path=(
            "CLI/Menu -> CommandService -> Task target/Next selection",
            "ctx.tasks.start() -> RuntimeClient/Local IPC -> TaskService.start()",
            "TaskService -> CalDAVAdapter; Activity/hook side effects happen after Core action",
        ),
        requires=(
            "No other Task may currently be active.",
            "The Task must not be completed or cancelled.",
        ),
        writes=(
            "CalDAV VTODO: sets the Task to STATUS:IN-PROCESS.",
            "CalDAV Work VEVENT: opens an actual-work interval when a Work Log collection is configured.",
            "Activity Journal (SQLite): records task_started.",
        ),
        does_not=("Does not rewrite the planned start time (DTSTART).",),
        side_effects=(
            "Emits task.started; enabled extensions may enqueue secondary logs such as WordPress work-session entries.",
        ),
        verify=("current", "history task <task>", "history pending", "history wordpress"),
        examples=("start", "start Anki", "start 1"),
    ),
    "pause": CommandSemantics(
        usage="pause",
        meaning=(
            "Pause the Task you are actually working on now. It does not accept an "
            "arbitrary planned Task name."
        ),
        path=(
            "CLI/Menu -> CommandService -> Session current Task",
            "ctx.tasks.pause() -> RuntimeClient/Local IPC -> TaskService.pause()",
            "TaskService -> CalDAV Work Log/Activity lifecycle",
        ),
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
        side_effects=(
            "Emits task.paused; enabled extensions may enqueue a WordPress/Outbox work-session log.",
        ),
        verify=("current", "resume", "history task <task>", "history pending", "history wordpress"),
        examples=("pause",),
    ),
    "resume": CommandSemantics(
        usage="resume",
        meaning="Continue work that this Assistant previously paused.",
        path=(
            "CLI/Menu -> CommandService -> paused-Task selection",
            "ctx.tasks.resume() -> RuntimeClient/Local IPC -> TaskService.resume()",
            "TaskService -> CalDAV Work Log/Activity lifecycle",
        ),
        requires=(
            "No other Task may currently be active.",
            "At least one previously paused Task must exist.",
        ),
        writes=(
            "CalDAV Work VEVENT: opens a new actual-work interval when Work Log is configured.",
            "Activity Journal (SQLite): records task_resumed.",
        ),
        does_not=("Does not rewrite planned DTSTART; the VTODO remains STATUS:IN-PROCESS.",),
        side_effects=(
            "Emits task.resumed; enabled extensions may enqueue a WordPress/Outbox work-session log.",
        ),
        verify=("current", "history task <task>", "history pending", "history wordpress"),
        examples=("resume",),
    ),
    "done": CommandSemantics(
        usage="done [task name | list number]",
        meaning="Mark a Task authoritatively complete. Alias: complete.",
        path=(
            "CLI/Menu -> CommandService -> Task target",
            "ctx.tasks.complete() -> RuntimeClient/Local IPC -> TaskService.complete()",
            "TaskService -> CalDAVAdapter -> ActionResult; Activity/Undo remain auxiliary",
        ),
        writes=(
            "CalDAV VTODO: STATUS=COMPLETED, completed=true, completion timestamp, and standard completion fields through the adapter.",
            "CalDAV Work VEVENT: closes the current work interval if this Task is active and Work Log is configured.",
            "Activity Journal (SQLite): records task_completed.",
        ),
        does_not=("WordPress success is not required for Task completion to succeed.",),
        side_effects=(
            "Completion logging may enqueue a human-readable summary through the WordPress Outbox.",
        ),
        verify=("history task <task>", "history pending", "history wordpress", "undo"),
        examples=("done", "done Report", "complete 1"),
    ),
    "edit": CommandSemantics(
        usage="edit [task name | list number]",
        meaning="Edit planned Task facts such as title, due date, or priority.",
        path=(
            "CLI/Menu -> CommandService -> Task selector -> PromptKit field prompt",
            "TemporalParser/validation when needed -> ctx.tasks.update()",
            "RuntimeClient/Local IPC -> TaskService.update() -> CalDAVAdapter",
        ),
        writes=(
            "CalDAV VTODO fields selected by the user.",
            "Activity Journal records the successful planning change.",
        ),
        does_not=("Does not mean start/pause/resume actual work.",),
        verify=("tasks or today", "history task <task>", "undo"),
        examples=("edit", "edit Anki", "edit 1"),
    ),
    "add": CommandSemantics(
        usage="add [task|event] [title]",
        meaning="Create a real CalDAV Task or Event through the shared guided prompts.",
        path=(
            "CLI/Menu -> CommandService -> CrudActions.add -> PromptKit/TemporalParser",
            "ctx.tasks.create()/ctx.events.create() -> RuntimeClient/Local IPC",
            "TaskService/EventService -> CalDAVAdapter -> configured collection",
        ),
        writes=("CalDAV VTODO or VEVENT in the configured collection.",),
        does_not=("Does not create a shadow Task/Event database in SQLite.",),
        verify=("tasks", "events", "Check the same object in another CalDAV client."),
        examples=("add", "add task Report", "add event Parent meeting"),
    ),
    "tasks": CommandSemantics(
        usage="tasks",
        meaning="List Tasks and make every displayed number an active Task reference.",
        path=(
            "CLI/Menu -> CommandService -> CrudActions.tasks -> ctx.tasks.list()",
            "RuntimeClient/Local IPC -> TaskService/CalDAV read",
            "Exact displayed objects -> Session.last_items -> numbered presenter",
        ),
        writes=("Session.last_items only (ephemeral reference context); Task facts are unchanged.",),
        does_not=("Displayed numbers are not decorative; they refer to the exact displayed objects until another numbered list replaces the context.",),
        verify=("After tasks, run edit <number> and Back without saving, or use start/done when you intend the mutation."),
        examples=("tasks", "tasks; then edit 3"),
    ),
    "events": CommandSemantics(
        usage="events",
        meaning="List ordinary Events and make every displayed number an active Event reference.",
        path=(
            "CLI/Menu -> CommandService -> CrudActions.events -> ctx.events.list()",
            "RuntimeClient/Local IPC -> EventService/CalDAV read",
            "Exact displayed objects -> Session.last_items -> numbered presenter",
        ),
        writes=("Session.last_items only (ephemeral reference context); Event facts are unchanged.",),
        verify=("After events, run edit-event <number> and Back without saving."),
        examples=("events", "events; then edit-event 2"),
    ),
    "edit-event": CommandSemantics(
        usage="edit-event [event name | list number]",
        meaning="Edit one Event through the same PromptKit/TemporalParser and Event service path.",
        path=(
            "CLI/Menu -> CommandService -> Event target -> PromptKit",
            "TemporalParser/validation when needed -> ctx.events.update()",
            "RuntimeClient/Local IPC -> EventService.update() -> CalDAVAdapter",
        ),
        writes=("Selected CalDAV VEVENT fields.",),
        verify=("events", "Check the VEVENT in another CalDAV client."),
        examples=("edit-event", "edit-event 2"),
    ),
    "remove": CommandSemantics(
        usage="remove [task|event] [name | list number]",
        meaning="Delete a Task or Event only after explicit danger confirmation.",
        path=(
            "CLI/Menu -> CommandService -> Task/Event target -> PromptKit confirmation",
            "ctx.tasks.delete()/ctx.events.delete() -> RuntimeClient/Local IPC",
            "TaskService/EventService -> CalDAVAdapter; UndoManager records supported restore state",
        ),
        requires=("Explicit confirmation.", "A current active Task must be paused/completed before deletion."),
        writes=("Deletes the selected CalDAV object; records supported Undo state.",),
        verify=("tasks or events", "undo immediately if deletion was unintended."),
        examples=("remove", "remove task 3", "remove event 2"),
    ),
    "log": CommandSemantics(
        usage="log [text]",
        meaning="Write a human long-term note through the WordPress logging path.",
        path=(
            "CLI/Menu -> CommandService -> ctx.wordpress.log() -> WordPressService",
            "Durable WordPress Outbox enqueue -> immediate WordPressAdapter delivery attempt",
            "Outbox item -> sent on success, retained pending on failure -> ActionResult",
        ),
        writes=(
            "WordPress Outbox: durable request used for reliable delivery.",
            "WordPress daily post: updated/created when delivery succeeds.",
        ),
        does_not=("Does not change Task or Event state.",),
        verify=("history pending", "history wordpress"),
        examples=("log Finished chapter 3", "log"),
    ),
    "history": CommandSemantics(
        usage="history [today | task [name] | wordpress | pending]",
        meaning=(
            "Inspect what really happened at each storage layer instead of treating "
            "every kind of log as the same thing."
        ),
        path=(
            "CLI/Menu -> CommandService -> NavigationActions.history",
            "today/task -> ActivityService; wordpress -> real WordPress daily post; pending -> WordPress Outbox",
        ),
        writes=(),
        side_effects=(
            "history today/task reads the local Activity Journal.",
            "history wordpress reads real WordPress post content.",
            "history pending reads the durable WordPress Outbox.",
        ),
        examples=("history today", "history task Anki", "history wordpress", "history pending"),
    ),
    "menu": CommandSemantics(
        usage="menu",
        meaning=(
            "Open real stack-based multi-level navigation. Menu leaves dispatch to the "
            "same canonical commands; this is not a second business-logic implementation."
        ),
        path=(
            "CLI -> NavigationActions navigation stack -> shared PromptKit/Menu",
            "NavigationCommand leaf -> ctx.commands.run(canonical command) -> same handler as direct CLI",
        ),
        writes=(),
        does_not=("0/back only pops one navigation level; ordinary command text is handed back to the normal REPL.",),
        verify=("menu -> Work -> Back should return to root, not REPL.",),
        examples=("menu", "m", "Press Enter at the empty REPL prompt."),
    ),
    "settings": CommandSemantics(
        usage="settings [category/action]",
        meaning="Inspect or change validated Assistant configuration without editing configuration files by hand.",
        path=(
            "CLI/Menu -> SettingsActions -> ctx.settings validated API/Runtime bridge",
            "Commands/Extensions panels -> the same canonical CommandService handlers for those subsystems",
        ),
        writes=("Only the validated setting selected by the user; secrets use dedicated secure flows.",),
        does_not=("Does not edit SQLite/config files directly from the CLI presentation layer.",),
        verify=("settings", "settings get <key>", "settings caldav status"),
    ),
    "background": CommandSemantics(
        usage="background [status | start | stop | restart | enable | disable]",
        meaning=(
            "Inspect or manage the lightweight Assistant background service used for "
            "reminders, maintenance, IPC, and reliable delivery."
        ),
        path=(
            "CLI -> BackgroundActions -> RuntimeClient and AutostartManager",
            "RuntimeClient -> local IPC/service lifecycle; AutostartManager -> platform user autostart",
        ),
        verify=("background status",),
    ),
    "undo": CommandSemantics(
        usage="undo",
        meaning="Undo the most recent supported mutation recorded by UndoManager.",
        path=(
            "CLI -> CommandService -> runtime.call('undo.last') -> Local IPC",
            "Background runtime -> UndoManager -> original Task/Event service/CalDAV restore path",
        ),
        writes=("Reapplies the stored previous authoritative state for supported operations.",),
        verify=("tasks or events", "Check the restored object in CalDAV."),
    ),
    "extensions": CommandSemantics(
        usage="extensions",
        meaning="List installed Assistant extensions and their real lifecycle state.",
        path=("CLI/Settings -> CommandService -> ExtensionActions -> ExtensionManager",),
        writes=(),
        verify=("extension info <name>", "extension errors"),
    ),
    "extension": CommandSemantics(
        usage="extension <add|new|load|enable|disable|reload|unload|errors|info|guide> ...",
        meaning="Manage an extension lifecycle without modifying Core source files.",
        path=(
            "CLI/Settings -> CommandService -> ExtensionActions -> ExtensionManager",
            "ExtensionManager -> discovery/load/enable/disable/reload/error isolation",
        ),
        verify=("extensions", "extension info <name>", "extension errors"),
    ),
    "api": CommandSemantics(
        usage="api [interface | exists | search | list] ...",
        meaning="Browse the actual exported stable Public Python API instead of a hand-written fake catalog.",
        path=(
            "CLI -> CommandService -> APIHelpAction",
            "APIHelpAction -> api_catalog/api_describe/api_exists/api_find generated from real public exports/Protocols",
        ),
        writes=(),
        verify=("api exists <interface>", "Import the shown public symbol and use its displayed signature."),
        examples=("api easy.complete", "api exists Task.start_task", "api list full"),
    ),
    "help": CommandSemantics(
        usage="help [command]",
        meaning=(
            "List commands or explain one command's human meaning, runtime path, "
            "requirements, writes, non-effects, side effects, and verification paths."
        ),
        path=("CLI -> CommandService/CommandRegistry metadata -> command semantics renderer",),
        writes=(),
        examples=("help", "help pause", "help done", "help tasks"),
    ),
    "clear": CommandSemantics(
        usage="clear",
        meaning="Clear only the terminal presentation using the developer_tools extension.",
        path=("CLI -> CommandRegistry -> developer_tools.clear_screen -> ANSI terminal output",),
        writes=(),
        does_not=("Does not delete Task/Event/Activity/WordPress data.",),
        verify=("The terminal clears; normal data queries still return the same data."),
        examples=("clear",),
    ),
    "shell": CommandSemantics(
        usage="shell [program args...]",
        meaning="Temporarily run an external command or an interactive foreground shell, then return to Assistant.",
        path=(
            "CLI -> CommandRegistry -> developer_tools.run_external",
            "subprocess.run(argv, shell=False) or configured interactive shell",
        ),
        side_effects=("The external program can have its own effects; Assistant does not guess or wrap them as Core changes.",),
        verify=("Inspect the child process exit/output; exit the child shell to return to Assistant."),
        examples=("shell git status", "shell pytest -q", "shell bash"),
    ),
    "run": CommandSemantics(
        usage="run [-b|--background] <program args...> [in background]",
        meaning="Run an explicit external process in foreground or detached background mode.",
        path=(
            "CLI -> CommandRegistry -> developer_tools.run_command",
            "foreground -> subprocess.run; background -> subprocess.Popen + persistent per-user output log",
        ),
        side_effects=("The external program can have its own effects; no shell=True interpretation is added implicitly.",),
        verify=("Foreground: inspect exit code/output.", "Background: inspect the printed PID and output-log path."),
        examples=("run git status", "run -b python worker.py", "run bash -lc 'echo hello | cat'"),
    ),
    "exit": CommandSemantics(
        usage="exit",
        meaning="Leave the interactive CLI process; alias: quit/q.",
        path=("CLI -> CommandService -> internal EXIT_REPL signal -> REPL exits",),
        writes=(),
        does_not=("Does not stop the independent background Assistant service.",),
        verify=("caldav-assistant background status",),
        examples=("exit", "q"),
    ),
}


def format_command_help(entry: Any) -> str:
    name = str(getattr(entry, "name", "") or "").strip()
    description = (
        str(getattr(entry, "description", "") or "").strip() or "No description."
    )
    aliases = ", ".join(getattr(entry, "aliases", ()) or ()) or "-"
    source = str(getattr(entry, "source", "") or "-")
    spec = _SEMANTICS.get(name)
    if spec is None:
        return "\n".join(
            [
                name,
                f"  {description}",
                "",
                "Runtime path:",
                f"  - CLI -> CommandRegistry -> {source} handler",
                "  - The handler may change Core data only through services it explicitly calls.",
                "",
                "Verify with:",
                "  - Inspect this extension/command's guide and the relevant Task/Event/history/settings view.",
                "",
                f"aliases: {aliases}",
                f"source: {source}",
            ]
        )

    lines = [
        name,
        f"  {description}",
        "",
        f"Usage: {spec.usage}",
        f"Meaning: {spec.meaning}",
    ]
    sections = (
        ("Runtime path", spec.path),
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
        "Use 'help <command>' for runtime path, meaning, data writes, side effects, and verification.",
        "Visible numbers from today/tasks/events are actionable references for compatible commands.",
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
