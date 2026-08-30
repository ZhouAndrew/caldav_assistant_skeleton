"""Composable built-in CLI actions.

MODULE CONTRACT
- Imports/calls: AssistantContext public namespaces through ``ctx`` only.
- Provides: ``BuiltinActions`` and ``register_cli_builtin_commands``.
- Called by: CommandRegistry/CommandService wiring.
- May call: PromptKit through ``ctx.ui`` and public Task/Agenda/WordPress APIs.
- Must not: instantiate TaskService/EventService/CalDAVAdapter, access IPC/SQLite/XML,
  print directly, or become a giant command dispatcher.

CLI lifecycle words describe human work, not CalDAV scheduling fields:
``start`` = begin working now; ``pause`` = pause current work; ``resume`` = continue
something previously paused. Planned DTSTART remains an edit/scheduling concern.
"""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from typing import Any, Callable

from ...api.v1.errors import AmbiguousError, ValidationError
from .worklog_setup import WorkLogSetup


@dataclass(frozen=True, slots=True)
class _ExitSignal:
    """Internal REPL control result; never crosses the Core service boundary."""


EXIT_REPL = _ExitSignal()


@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    """Declarative metadata used to register one protected core command."""

    name: str
    handler_name: str
    description: str
    aliases: tuple[str, ...] = ()


_COMMAND_OPERATION_GUIDE: dict[str, tuple[str, str, str]] = {
    "today": (
        "REPL/one-shot → CommandRegistry → Agenda API → AgendaService/Engine → Task/Event reads → presenter.",
        "Read-only. CalDAV is authoritative; experimental cache may serve a labelled verified snapshot.",
        "Run `today` again; use `settings cache status` to see whether a cache or CalDAV served recent reads.",
    ),
    "next": (
        "REPL/one-shot → CommandRegistry → Agenda.next → NextEngine → Task/Event reads → presenter.",
        "Read-only recommendation; it does not start or modify the recommended Task.",
        "Compare `next`, `today`, and `current`.",
    ),
    "current": (
        "REPL/one-shot → CommandRegistry → Session current-task pointer + Activity history → Task presentation.",
        "Read-only. CalDAV STATUS remains Task truth; Session only identifies which in-process Task is current.",
        "Run `history task <name>` to see start/pause/resume timestamps.",
    ),
    "start": (
        "REPL → CommandRegistry → target/Next selection → Task API → Runtime/IPC → TaskService → CalDAVAdapter; Activity/hook side effects follow Core action.",
        "Writes the Task work state to CalDAV and records Assistant activity. Configured extensions may add independent logging hooks.",
        "Run `current`, then `history task <name>`; use your CalDAV client to confirm STATUS:IN-PROCESS.",
    ),
    "pause": (
        "REPL → CommandRegistry → Session current Task → Task API → Runtime/IPC → TaskService → CalDAVAdapter + Activity.",
        "Pauses only the Task currently being worked on; it does not change planned DTSTART.",
        "Run `current` and `history task <name>`; the Task should no longer be current and a task_paused activity should exist.",
    ),
    "resume": (
        "REPL → CommandRegistry → paused-Task selection → Task API → Runtime/IPC → TaskService → CalDAVAdapter + Activity.",
        "Restores actual work state; it does not rewrite the planned start date.",
        "Run `current` and `history task <name>`; the latest lifecycle entry should be task_resumed.",
    ),
    "done": (
        "REPL → CommandRegistry → Task target → Task API → Runtime/IPC → TaskService → CalDAVAdapter → ActionResult.",
        "CalDAV is completed first (STATUS:COMPLETED / completed fields). WordPress cannot block Task completion.",
        "Run `history task <name>` and inspect the Task in CalDAV; `undo` reports/restores the latest reversible change.",
    ),
    "edit": (
        "REPL → CommandRegistry → Task selector → field Prompt → TemporalParser/validation → Task API → Runtime/IPC → TaskService → CalDAVAdapter.",
        "Writes only the chosen Task field. The mutation participates in the shared Undo path.",
        "Run `tasks`/`today` and inspect the Task in CalDAV; use `undo` if the last change was wrong.",
    ),
    "add": (
        "REPL → CommandRegistry → Task/Event choice → PromptKit/TemporalParser → Task/Event API → Runtime/IPC → Service → CalDAVAdapter.",
        "Creates a real VTODO or VEVENT in the configured CalDAV collection.",
        "Run `tasks` or `events`, then verify the object in another CalDAV client.",
    ),
    "tasks": (
        "REPL → CommandRegistry → Task API list → Runtime/IPC → TaskService/CalDAV read → numbered presenter + Session.last_items.",
        "Read-only. Every displayed number becomes an active Task reference for `edit N`, `start N`, `done N`, etc.",
        "Immediately run `edit N`, `start N`, or `done N`; the number resolves to the exact object from the displayed list.",
    ),
    "events": (
        "REPL → CommandRegistry → Event API list → Runtime/IPC → EventService/CalDAV read → numbered presenter + Session.last_items.",
        "Read-only. Every displayed number becomes an active Event reference.",
        "Immediately run `edit-event N` or `remove event N`.",
    ),
    "edit-event": (
        "REPL → CommandRegistry → Event target → PromptKit/TemporalParser → Event API → Runtime/IPC → EventService → CalDAVAdapter.",
        "Writes the chosen VEVENT field through the shared Event service.",
        "Run `events` and verify the Event in another CalDAV client.",
    ),
    "remove": (
        "REPL → CommandRegistry → Task/Event target → danger confirmation → Task/Event API → Runtime/IPC → Service → CalDAVAdapter.",
        "Deletes the CalDAV object and records undo information; active current Tasks are protected from deletion.",
        "Run `tasks`/`events`; use `undo` immediately if the deletion was unintended.",
    ),
    "log": (
        "REPL → CommandRegistry → WordPress API → WordPressService → durable local Outbox → immediate WordPress transport attempt → ActionResult.",
        "The text is written to Outbox before network delivery. If delivery fails it remains pending instead of being lost.",
        "Run `history wordpress` to read the real daily post and `history pending` to see undelivered Outbox items.",
    ),
    "history": (
        "REPL → CommandRegistry → selected observability source: ActivityService (SQLite), Task activity, real WordPress post_content, or WordPress Outbox.",
        "Read-only diagnostic command. Activity is not Task truth and WordPress is not Task truth.",
        "Use `history today`, `history task NAME`, `history wordpress`, and `history pending` to cross-check each store independently.",
    ),
    "menu": (
        "REPL → Menu/Choice navigation → the same CommandService.run() used by direct commands.",
        "Menu has no business logic of its own. `0/back` returns one menu level; typing a normal command hands it back to the REPL.",
        "Compare a menu action with the equivalent direct command; results and side effects must match.",
    ),
    "settings": (
        "REPL → SettingsActions → public Settings API/Runtime bridge. Commands and Extensions panels dispatch their canonical management commands.",
        "Validated settings are stored through SettingsService; secrets use dedicated flows. Settings does not edit SQLite/config files directly.",
        "Use `settings get KEY`, `settings list`, CalDAV test/status, or reopen the panel to confirm the saved value.",
    ),
    "background": (
        "one-shot/REPL → BackgroundActions → RuntimeClient + platform AutostartManager → local Assistant Service.",
        "Controls service process and reminder autostart; it does not implement Task logic separately.",
        "Run `background status`; it reports service state, reminder autostart, maintenance state and PID when running.",
    ),
    "undo": (
        "REPL → Undo CLI → Runtime/IPC → UndoManager → original Task/Event service/CalDAV mutation path.",
        "Reverses the latest reversible Task/Event change using durable undo state.",
        "Re-run `tasks`/`events` and verify in CalDAV after undo.",
    ),
    "extensions": (
        "REPL → CommandRegistry → ExtensionActions → ExtensionManager discovery/state list.",
        "Read-only list of official and user extensions with real lifecycle status.",
        "Use `extension info NAME` and `extension errors [NAME]` for details.",
    ),
    "extension": (
        "REPL → CommandRegistry → ExtensionActions → ExtensionManager → load/enable/disable/reload/unload/new/error operations.",
        "Lifecycle changes use the same manager that loads extension commands/hooks; one extension failure is isolated from Core.",
        "Run `extensions`, `extension info NAME`, and `extension errors NAME`.",
    ),
    "api": (
        "REPL → Public API catalog/introspection → signatures/existence/usage presentation.",
        "Read-only developer aid; it does not bypass or replace the public API.",
        "Import the shown symbol from `caldav_assistant.easy`, `caldav_assistant.api`, or `caldav_assistant.api.v1` and run its documented example.",
    ),
    "clear": (
        "REPL → developer_tools extension command → terminal clear escape/OS terminal operation.",
        "Presentation-only; no CalDAV, WordPress, Activity, or settings data changes.",
        "The screen clears; `history` and Task/Event data remain unchanged.",
    ),
    "shell": (
        "REPL → developer_tools extension → foreground subprocess/interactive shell → return to the same Assistant REPL.",
        "External process effects are whatever that process performs; Assistant Core data is not implicitly changed.",
        "Exit the child shell/process and confirm the Assistant prompt returns; inspect the external command's own exit/output.",
    ),
    "run": (
        "REPL → developer_tools extension → foreground or detached subprocess; detached output is preserved in its run log.",
        "External command effects are independent from CalDAV Assistant unless the invoked program changes shared resources.",
        "Inspect the command exit/output or its background run log, then use normal Assistant query commands for Assistant state.",
    ),
    "help": (
        "REPL → CommandRegistry metadata + command operation guide → presenter.",
        "Read-only. It explains the real handler path, persistent effects and verification instead of merely restating the command name.",
        "Run `help <command>` for any registered command.",
    ),
    "exit": (
        "REPL → internal exit signal → CLI process exits. Background Service remains independent.",
        "No Task/Event mutation and no forced background-service stop.",
        "Run `caldav-assistant background status` after leaving the REPL if you want to confirm reminders remain active.",
    ),
}


class BuiltinActions:
    """Small CLI action bricks composed only from the frozen public namespaces."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def _show(self, value: Any) -> None:
        show = getattr(self.ctx.ui, "show", None)
        if callable(show):
            show(value)

    @staticmethod
    def _summary(value: Any) -> str:
        text = getattr(value, "summary", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        value_id = getattr(value, "id", None)
        if value_id:
            return str(value_id)
        return str(value)

    @staticmethod
    def _join_text(parts: tuple[Any, ...], *, label: str) -> str:
        if not parts:
            raise ValidationError(f"{label} must not be empty")
        if not all(isinstance(part, str) for part in parts):
            raise ValidationError(f"{label} must be text")
        value = " ".join(part.strip() for part in parts if part.strip()).strip()
        if not value:
            raise ValidationError(f"{label} must not be empty")
        return value

    def _ambiguous_task_choice(self, query: str) -> Any:
        candidates = [
            task
            for task in self.ctx.tasks.list()
            if query.casefold() in self._summary(task).casefold()
        ]
        if not candidates:
            raise AmbiguousError(query)
        choose = getattr(self.ctx.ui, "choose", None)
        if not callable(choose):
            raise AmbiguousError(query)
        return choose(
            f"Multiple tasks match: {query}",
            candidates,
            item_label=lambda task: self._summary(task),
        )

    def _task_from_parts(self, parts: tuple[Any, ...]) -> Any:
        if not parts:
            return self.ctx.ui.choose_task()
        if len(parts) == 1 and not isinstance(parts[0], str):
            return parts[0]
        query = self._join_text(parts, label="Task")
        try:
            return self.ctx.tasks.find(query)
        except AmbiguousError:
            return self._ambiguous_task_choice(query)

    def _session_current_task(self) -> Any:
        session = getattr(self.ctx, "session", None)
        getter = getattr(session, "current_task", None)
        return getter() if callable(getter) else None

    def _session_paused_tasks(self) -> list[Any]:
        session = getattr(self.ctx, "session", None)
        getter = getattr(session, "paused_tasks", None)
        return list(getter() or ()) if callable(getter) else []

    def _current_work_since(self, task: Any) -> Any:
        activity = getattr(self.ctx, "activity", None)
        reader = getattr(activity, "for_task", None)
        if not callable(reader):
            return None
        lifecycle = {"task_started", "task_resumed", "task_paused", "task_completed", "task_deleted"}
        try:
            items = [item for item in (reader(task) or ()) if getattr(item, "action", None) in lifecycle and getattr(item, "timestamp", None) is not None]
        except Exception:
            return None
        if not items:
            return None
        latest = max(items, key=lambda item: getattr(item, "timestamp"))
        if getattr(latest, "action", None) not in {"task_started", "task_resumed"}:
            return None
        return getattr(latest, "timestamp", None)

    def _recommended_task(self) -> Any:
        try:
            result = self.ctx.agenda.next(kind="task")
        except TypeError:
            result = self.ctx.agenda.next()
        value = getattr(result, "value", result)
        if value is None or not hasattr(value, "status") or bool(getattr(value, "completed", False)) or str(getattr(value, "status", "")) == "CANCELLED":
            return None
        return value

    def _ensure_worklog_ready(self) -> bool:
        settings = getattr(self.ctx, "settings", None)
        if settings is None or not callable(getattr(settings, "caldav_collections", None)):
            return True
        return WorkLogSetup(self.ctx).ensure()

    def _explain_task_action(self, verb: str, task: Any, **details: Any) -> None:
        text = f"{verb} → {self._summary(task)}"
        visible = [f"{key}: {value}" for key, value in details.items() if value is not None]
        if visible:
            text += "; " + "; ".join(visible)
        self._show(text)

    @staticmethod
    def _no_args(name: str, parts: tuple[Any, ...]) -> None:
        if parts:
            raise ValidationError(f"{name} does not take arguments")

    def today(self, *parts: Any) -> Any:
        self._no_args("today", parts)
        return self.ctx.agenda.today()

    def next(self, *parts: Any) -> Any:
        self._no_args("next", parts)
        return self.ctx.agenda.next()

    def current(self, *parts: Any) -> Any:
        self._no_args("current", parts)
        task = self._session_current_task()
        if task is None:
            paused = self._session_paused_tasks()
            if paused:
                return "No task is active right now. You have paused work; use 'resume' to continue it."
            return "No task is active right now. Use 'start' to begin working on the recommended task."
        view = copy(task)
        working_since = self._current_work_since(task)
        if working_since is not None:
            setattr(view, "_assistant_working_since", working_since)
        return view

    def done(self, *target_parts: Any) -> Any:
        if target_parts:
            task = self._task_from_parts(target_parts)
        else:
            task = self._session_current_task()
            if task is None:
                task = self.ctx.ui.choose_task()
        if task is None:
            return None
        self._explain_task_action("Complete", task)
        return self.ctx.tasks.complete(task)

    def start(self, *target_parts: Any) -> Any:
        current = self._session_current_task()
        if current is not None:
            if target_parts:
                requested = self._task_from_parts(target_parts)
                if getattr(requested, "id", None) == getattr(current, "id", None):
                    return f"Already working on: {self._summary(current)}"
            raise ValidationError(f"You are already working on '{self._summary(current)}'. Pause or complete it before starting another task.")
        if target_parts:
            task = self._task_from_parts(target_parts)
        else:
            task = self._recommended_task()
            if task is None:
                raise ValidationError("No actionable task is currently recommended. Use 'start <task name>' to choose a specific task.")
            confirm = getattr(self.ctx.ui, "confirm", None)
            if callable(confirm) and not confirm(f"Start working now on '{self._summary(task)}'?", default=True):
                return None
        if task is None:
            return None
        if not self._ensure_worklog_ready():
            return None
        self._explain_task_action("Start working", task)
        return self.ctx.tasks.start(task)

    def pause(self, *parts: Any) -> Any:
        if parts:
            raise ValidationError("pause does not take a task name; it pauses the task you are working on now")
        task = self._session_current_task()
        if task is None:
            raise ValidationError("No task is currently being worked on, so there is nothing to pause")
        self._explain_task_action("Pause current work", task)
        return self.ctx.tasks.pause(task)

    def resume(self, *parts: Any) -> Any:
        if parts:
            raise ValidationError("resume does not take an arbitrary task name; it continues work you previously paused")
        current = self._session_current_task()
        if current is not None:
            raise ValidationError(f"You are already working on '{self._summary(current)}'. Pause or complete it before resuming something else.")
        paused = self._session_paused_tasks()
        if not paused:
            raise ValidationError("There is no paused work to resume")
        if len(paused) == 1:
            task = paused[0]
        else:
            task = self.ctx.ui.choose("Resume which paused task?", paused, item_label=lambda item: self._summary(item))
        if task is None:
            return None
        self._explain_task_action("Resume work", task)
        return self.ctx.tasks.resume(task)

    def _edit_due(self, task: Any) -> Any:
        due = self.ctx.ui.ask_date("New due date")
        if due is None:
            return None
        self._explain_task_action("Edit", task, due=due)
        return self.ctx.tasks.update(task, due=due)

    def _edit_title(self, task: Any) -> Any:
        summary = self.ctx.ui.ask_text("New title")
        if summary is None:
            return None
        if not isinstance(summary, str) or not summary.strip():
            raise ValidationError("Task title must not be empty")
        summary = summary.strip()
        self._explain_task_action("Edit", task, title=summary)
        return self.ctx.tasks.update(task, summary=summary)

    def _edit_priority(self, task: Any) -> Any:
        raw = self.ctx.ui.ask_text("New priority (0-9)")
        if raw is None:
            return None
        try:
            priority = int(str(raw).strip())
        except (TypeError, ValueError) as exc:
            raise ValidationError("Priority must be an integer from 0 to 9") from exc
        if not 0 <= priority <= 9:
            raise ValidationError("Priority must be an integer from 0 to 9")
        self._explain_task_action("Edit", task, priority=priority)
        return self.ctx.tasks.update(task, priority=priority)

    def edit(self, *target_parts: Any) -> Any:
        task = self._task_from_parts(target_parts)
        if task is None:
            return None
        fields: dict[str, Callable[[Any], Any]] = {"Due date": self._edit_due, "Title": self._edit_title, "Priority": self._edit_priority}
        selected = self.ctx.ui.choose("Modify what?", tuple(fields))
        if selected is None:
            return None
        action = fields.get(str(selected))
        if action is None:
            raise ValidationError(f"Unsupported edit field: {selected}")
        return action(task)

    def edit_due(self, task: Any = None, due: Any = None) -> Any:
        if task is None:
            task = self.ctx.ui.choose_task()
        elif isinstance(task, str):
            task = self._task_from_parts((task,))
        if task is None:
            return None
        if due is None:
            due = self.ctx.ui.ask_date("New due date")
        elif isinstance(due, str):
            due = self.ctx.time.parse_date(due, bias="future")
        if due is None:
            return None
        self._explain_task_action("Edit", task, due=due)
        return self.ctx.tasks.update(task, due=due)

    def log(self, *text_parts: Any) -> Any:
        if text_parts:
            text = self._join_text(text_parts, label="Log text")
        else:
            text = self.ctx.ui.ask_text("Log")
            if text is None:
                return None
            if not isinstance(text, str) or not text.strip():
                raise ValidationError("Log text must not be empty")
            text = text.strip()
        self._show(f"Log → {text}")
        self._show("Steps: validate text → save durable WordPress Outbox item → try immediate WordPress upload. If upload fails, the Outbox item stays pending.")
        result = self.ctx.wordpress.log(text)
        self._show("Check: `history wordpress` reads the real daily post; `history pending` shows anything not delivered.")
        return result

    def help(self, *name_parts: Any) -> str:
        if name_parts:
            name = self._join_text(name_parts, label="Command")
            entry = self.ctx.commands.resolve(name)
            aliases = ", ".join(entry.aliases) if entry.aliases else "-"
            description = entry.description or "No description."
            guide = _COMMAND_OPERATION_GUIDE.get(entry.name)
            if guide is None:
                flow = f"REPL/one-shot → CommandRegistry → {entry.source} handler → public services used by that handler."
                effects = "Effects are defined by this extension/command handler; Core data is changed only through services it explicitly calls."
                check = "Inspect the command/extension documentation and use the relevant Task/Event/history/settings query to verify its effect."
            else:
                flow, effects, check = guide
            return (
                f"{entry.name}\n"
                f"  Purpose: {description}\n"
                f"  aliases: {aliases}\n"
                f"  source: {entry.source}\n"
                f"  Runtime: {flow}\n"
                f"  Effects: {effects}\n"
                f"  Verify: {check}"
            )
        lines = ["Commands:"]
        for entry in self.ctx.commands.list():
            if entry.name == "edit-due":
                continue
            description = f" — {entry.description}" if entry.description else ""
            lines.append(f"  {entry.name}{description}")
        lines.extend(["", "Use `help <command>` for its runtime path, persistent effects, and verification steps.", "Visible numbers from `today`, `tasks`, and `events` are actionable references where the command expects that object type."])
        return "\n".join(lines)

    def exit(self, *parts: Any) -> _ExitSignal:
        self._no_args("exit", parts)
        return EXIT_REPL


_BUILTINS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand("today", "today", "Show today's relevant tasks and events."),
    BuiltinCommand("next", "next", "Show the recommended next thing to do."),
    BuiltinCommand("current", "current", "Show the task you are working on now.", aliases=("now",)),
    BuiltinCommand("edit", "edit", "Change a task's title, due date, priority, or other planned details."),
    BuiltinCommand("done", "done", "Mark a task complete.", aliases=("complete",)),
    BuiltinCommand("start", "start", "Begin working on a task now."),
    BuiltinCommand("pause", "pause", "Pause the task you are working on now."),
    BuiltinCommand("resume", "resume", "Continue a task you previously paused."),
    BuiltinCommand("log", "log", "Save a long-term activity note through WordPressService."),
    BuiltinCommand("help", "help", "List commands or explain one command.", aliases=("?",)),
    BuiltinCommand("exit", "exit", "Leave the interactive CLI.", aliases=("quit", "q")),
    BuiltinCommand("edit-due", "edit_due", "Compatibility command: change one Task due date."),
)


def builtin_command_specs() -> tuple[BuiltinCommand, ...]:
    return _BUILTINS


def register_cli_builtin_commands(commands: Any, ctx: Any) -> None:
    actions = BuiltinActions(ctx)
    existing = set(commands.names(include_aliases=True))
    for spec in _BUILTINS:
        if spec.name in existing:
            continue
        collisions = set(spec.aliases) & existing
        aliases = () if collisions else spec.aliases
        commands.register_builtin(spec.name, getattr(actions, spec.handler_name), aliases=aliases, description=spec.description)
        existing.add(spec.name)
        existing.update(aliases)
