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
from .help_library import is_category, render_help_all, render_help_category, render_help_root
from .semantics import (
    attach_result_explanation,
    format_command_help,
    help_list_footer,
    lifecycle_explanation,
    log_explanation,
)
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
    def _same_task(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return False
        left_id = str(getattr(left, "id", "") or "").strip()
        right_id = str(getattr(right, "id", "") or "").strip()
        return bool(left_id and right_id and left_id == right_id)

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
        """Return the latest actual work-start instant from Activity Journal.

        DTSTART is the planned start and must never be reused as the answer to
        "when did I start working?". The journal is behaviour history only; the
        Session service still decides whether the Task is actually current.
        """
        activity = getattr(self.ctx, "activity", None)
        reader = getattr(activity, "for_task", None)
        if not callable(reader):
            return None

        lifecycle = {
            "task_started",
            "task_resumed",
            "task_paused",
            "task_completed",
            "task_deleted",
        }
        try:
            items = [
                item
                for item in (reader(task) or ())
                if getattr(item, "action", None) in lifecycle
                and getattr(item, "timestamp", None) is not None
            ]
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
        if value is None:
            return None
        if not hasattr(value, "status"):
            return None
        if bool(getattr(value, "completed", False)):
            return None
        if str(getattr(value, "status", "")) == "CANCELLED":
            return None
        return value

    def _ensure_worklog_ready(self) -> bool:
        settings = getattr(self.ctx, "settings", None)
        if settings is None or not callable(getattr(settings, "caldav_collections", None)):
            return True
        return WorkLogSetup(self.ctx).ensure()

    def _explain_task_action(self, verb: str, task: Any, **details: Any) -> None:
        """Immediate acknowledgement before a mutation; final result explains effects."""
        text = f"{verb} → {self._summary(task)}"
        visible = [
            f"{key}: {value}"
            for key, value in details.items()
            if value is not None
        ]
        if visible:
            text += "; " + "; ".join(visible)
        self._show(text)

    def _lifecycle_result(
        self,
        action: str,
        task: Any,
        result: Any,
        *,
        was_current: bool | None = None,
    ) -> Any:
        return attach_result_explanation(
            result,
            lifecycle_explanation(
                self.ctx,
                action,
                task,
                result,
                was_current=was_current,
            ),
        )

    @staticmethod
    def _no_args(name: str, parts: tuple[Any, ...]) -> None:
        if parts:
            raise ValidationError(f"{name} does not take arguments")

    def _ask_future_date(self, prompt: str) -> Any:
        """Use the frozen TemporalParser future context for scheduling edits."""
        ask = getattr(self.ctx.ui, "ask_date", None)
        if not callable(ask):
            raise ValidationError(f"{prompt} requires date input support")
        try:
            return ask(prompt, bias="future")
        except TypeError:
            return ask(prompt)

    # ------------------------------------------------------------------
    # Query commands
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Task lifecycle commands
    # ------------------------------------------------------------------
    def done(self, *target_parts: Any) -> Any:
        current_before = self._session_current_task()
        if target_parts:
            task = self._task_from_parts(target_parts)
        else:
            task = current_before
            if task is None:
                task = self.ctx.ui.choose_task()
        if task is None:
            return None
        was_current = self._same_task(current_before, task)
        self._explain_task_action("Complete", task)
        result = self.ctx.tasks.complete(task)
        return self._lifecycle_result("done", task, result, was_current=was_current)

    def start(self, *target_parts: Any) -> Any:
        current = self._session_current_task()
        if current is not None:
            if target_parts:
                requested = self._task_from_parts(target_parts)
                if getattr(requested, "id", None) == getattr(current, "id", None):
                    return f"Already working on: {self._summary(current)}"
            raise ValidationError(
                f"You are already working on '{self._summary(current)}'. Pause or complete it before starting another task."
            )

        if target_parts:
            task = self._task_from_parts(target_parts)
        else:
            task = self._recommended_task()
            if task is None:
                raise ValidationError(
                    "No actionable task is currently recommended. Use 'start <task name>' to choose a specific task."
                )
            confirm = getattr(self.ctx.ui, "confirm", None)
            if callable(confirm):
                accepted = confirm(
                    f"Start working now on '{self._summary(task)}'?",
                    default=True,
                )
                if not accepted:
                    return None

        if task is None:
            return None
        if not self._ensure_worklog_ready():
            return None
        self._explain_task_action("Start working", task)
        result = self.ctx.tasks.start(task)
        return self._lifecycle_result("start", task, result)

    def pause(self, *parts: Any) -> Any:
        if parts:
            raise ValidationError(
                "pause does not take a task name; it pauses the task you are working on now"
            )
        task = self._session_current_task()
        if task is None:
            raise ValidationError("No task is currently being worked on, so there is nothing to pause")
        self._explain_task_action("Pause current work", task)
        result = self.ctx.tasks.pause(task)
        return self._lifecycle_result("pause", task, result, was_current=True)

    def resume(self, *parts: Any) -> Any:
        if parts:
            raise ValidationError(
                "resume does not take an arbitrary task name; it continues work you previously paused"
            )
        current = self._session_current_task()
        if current is not None:
            raise ValidationError(
                f"You are already working on '{self._summary(current)}'. Pause or complete it before resuming something else."
            )

        paused = self._session_paused_tasks()
        if not paused:
            raise ValidationError("There is no paused work to resume")
        if len(paused) == 1:
            task = paused[0]
        else:
            task = self.ctx.ui.choose(
                "Resume which paused task?",
                paused,
                item_label=lambda item: self._summary(item),
            )
        if task is None:
            return None
        self._explain_task_action("Resume work", task)
        result = self.ctx.tasks.resume(task)
        return self._lifecycle_result("resume", task, result)

    # ------------------------------------------------------------------
    # Edit command: scheduling/data editing, not work-session lifecycle
    # ------------------------------------------------------------------
    def _edit_due(self, task: Any) -> Any:
        due = self._ask_future_date("New due date")
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

        fields: dict[str, Callable[[Any], Any]] = {
            "Due date": self._edit_due,
            "Title": self._edit_title,
            "Priority": self._edit_priority,
        }
        selected = self.ctx.ui.choose("Modify what?", tuple(fields))
        if selected is None:
            return None
        action = fields.get(str(selected))
        if action is None:
            raise ValidationError(f"Unsupported edit field: {selected}")
        return action(task)

    def edit_due(self, task: Any = None, due: Any = None) -> Any:
        """Compatibility brick retained for older integrations.

        Normal users should use ``edit``; this command is intentionally hidden from
        the default help list so compatibility machinery does not become UX.
        """
        if task is None:
            task = self.ctx.ui.choose_task()
        elif isinstance(task, str):
            task = self._task_from_parts((task,))
        if task is None:
            return None

        if due is None:
            due = self._ask_future_date("New due date")
        elif isinstance(due, str):
            due = self.ctx.time.parse_date(due, bias="future")
        if due is None:
            return None

        self._explain_task_action("Edit", task, due=due)
        return self.ctx.tasks.update(task, due=due)

    # ------------------------------------------------------------------
    # Long-term log / shell utility commands
    # ------------------------------------------------------------------
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
        result = self.ctx.wordpress.log(text)
        return attach_result_explanation(result, log_explanation(text, result))

    def help(self, *name_parts: Any) -> str:
        entries = self.ctx.commands.list()
        if name_parts:
            name = self._join_text(name_parts, label="Command")
            key = name.strip().casefold()
            if key == "all":
                return render_help_all(entries)
            if is_category(key):
                return render_help_category(entries, key)
            entry = self.ctx.commands.resolve(name)
            return format_command_help(entry)

        return render_help_root(entries)

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
    BuiltinCommand("help", "help", "Browse categorized actions or explain one command.", aliases=("?",)),
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

        commands.register_builtin(
            spec.name,
            getattr(actions, spec.handler_name),
            aliases=aliases,
            description=spec.description,
        )
        existing.add(spec.name)
        existing.update(aliases)
