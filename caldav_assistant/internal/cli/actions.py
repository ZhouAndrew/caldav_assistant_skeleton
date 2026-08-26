"""Composable built-in CLI actions.

MODULE CONTRACT
- Imports/calls: AssistantContext public namespaces through ``ctx`` only.
- Provides: ``BuiltinActions`` and ``register_cli_builtin_commands``.
- Called by: CommandRegistry/CommandService wiring.
- May call: PromptKit through ``ctx.ui`` and public Task/Agenda/WordPress APIs.
- Must not: instantiate TaskService/EventService/CalDAVAdapter, access IPC/SQLite/XML,
  print directly, or become a giant command dispatcher.

The action layer contains small composition bricks.  Business mutations remain in the
authoritative Core services behind ``ctx.tasks`` / ``ctx.events`` / etc.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ...api.v1.errors import AmbiguousError, ValidationError


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

    # ------------------------------------------------------------------
    # Presentation / selection bricks
    # ------------------------------------------------------------------
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
        """Present candidates; never silently decides between ambiguous Tasks."""
        candidates = [
            task
            for task in self.ctx.tasks.list()
            if query.casefold() in self._summary(task).casefold()
        ]
        if not candidates:
            # Preserve the original stable Ambiguous/NotFound semantics upstream.
            raise AmbiguousError(query)
        choose = getattr(self.ctx.ui, "choose", None)
        if not callable(choose):
            raise AmbiguousError(query)
        return choose(f"Multiple tasks match: {query}", candidates)

    def _task_from_parts(self, parts: tuple[Any, ...]) -> Any:
        if not parts:
            return self.ctx.ui.choose_task()

        # Programmatic callers (notification / extension / tests) may already hold a
        # Task object.  CLI text callers arrive as strings.
        if len(parts) == 1 and not isinstance(parts[0], str):
            return parts[0]

        query = self._join_text(parts, label="Task")
        try:
            return self.ctx.tasks.find(query)
        except AmbiguousError:
            return self._ambiguous_task_choice(query)

    def _explain_task_action(self, verb: str, task: Any, **details: Any) -> None:
        text = f"{verb} → {self._summary(task)}"
        visible = [
            f"{key}: {value}"
            for key, value in details.items()
            if value is not None
        ]
        if visible:
            text += "; " + "; ".join(visible)
        self._show(text)

    @staticmethod
    def _no_args(name: str, parts: tuple[Any, ...]) -> None:
        if parts:
            raise ValidationError(f"{name} does not take arguments")

    # ------------------------------------------------------------------
    # Query commands
    # ------------------------------------------------------------------
    def today(self, *parts: Any) -> Any:
        self._no_args("today", parts)
        return self.ctx.agenda.today()

    def next(self, *parts: Any) -> Any:
        self._no_args("next", parts)
        return self.ctx.agenda.next()

    # ------------------------------------------------------------------
    # Task lifecycle commands
    # ------------------------------------------------------------------
    def done(self, *target_parts: Any) -> Any:
        task = self._task_from_parts(target_parts)
        if task is None:
            return None
        self._explain_task_action("Complete", task)
        return self.ctx.tasks.complete(task)

    def start(self, *target_parts: Any) -> Any:
        task = self._task_from_parts(target_parts)
        if task is None:
            return None
        self._explain_task_action("Start", task)
        return self.ctx.tasks.start(task)

    def pause(self, *target_parts: Any) -> Any:
        task = self._task_from_parts(target_parts)
        if task is None:
            return None
        self._explain_task_action("Pause", task)
        return self.ctx.tasks.pause(task)

    def resume(self, *target_parts: Any) -> Any:
        task = self._task_from_parts(target_parts)
        if task is None:
            return None
        self._explain_task_action("Resume", task)
        return self.ctx.tasks.resume(task)

    # ------------------------------------------------------------------
    # Edit command: Scratch-style composition, not a monolithic editor
    # ------------------------------------------------------------------
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
        """Compatibility brick retained for the existing ``edit-due`` registration."""
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
        return self.ctx.wordpress.log(text)

    def help(self, *name_parts: Any) -> str:
        if name_parts:
            name = self._join_text(name_parts, label="Command")
            entry = self.ctx.commands.resolve(name)
            aliases = ", ".join(entry.aliases) if entry.aliases else "-"
            description = entry.description or "No description."
            return (
                f"{entry.name}\n"
                f"  {description}\n"
                f"  aliases: {aliases}\n"
                f"  source: {entry.source}"
            )

        lines = ["Commands:"]
        for entry in self.ctx.commands.list():
            description = f" — {entry.description}" if entry.description else ""
            lines.append(f"  {entry.name}{description}")
        return "\n".join(lines)

    def exit(self, *parts: Any) -> _ExitSignal:
        self._no_args("exit", parts)
        return EXIT_REPL


_BUILTINS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand("today", "today", "Show today's agenda."),
    BuiltinCommand("next", "next", "Show the recommended next item."),
    BuiltinCommand("edit", "edit", "Interactively edit a Task using PromptKit bricks."),
    BuiltinCommand("done", "done", "Complete a Task.", aliases=("complete",)),
    BuiltinCommand("start", "start", "Start a Task."),
    BuiltinCommand("pause", "pause", "Pause a Task."),
    BuiltinCommand("resume", "resume", "Resume a Task."),
    BuiltinCommand("log", "log", "Write a long-term log through WordPressService."),
    BuiltinCommand("help", "help", "List commands or show command help.", aliases=("?",)),
    BuiltinCommand("exit", "exit", "Leave the interactive REPL.", aliases=("quit", "q")),
    # Retained for compatibility with the original scaffold/bootstrap.
    BuiltinCommand("edit-due", "edit_due", "Change one Task due date."),
)


def builtin_command_specs() -> tuple[BuiltinCommand, ...]:
    return _BUILTINS


def register_cli_builtin_commands(commands: Any, ctx: Any) -> None:
    """Register missing protected core commands into the *same* CommandRegistry.

    Existing protected commands from the original bootstrap are deliberately left in
    place.  This function does not override user/extension commands silently: any
    collision that is not already the same built-in name remains visible.
    """
    actions = BuiltinActions(ctx)
    existing = set(commands.names(include_aliases=True))

    for spec in _BUILTINS:
        if spec.name in existing:
            continue

        # A canonical core name must not silently steal an alias already registered by
        # another producer.
        collisions = set(spec.aliases) & existing
        if collisions:
            aliases = ()
        else:
            aliases = spec.aliases

        commands.register_builtin(
            spec.name,
            getattr(actions, spec.handler_name),
            aliases=aliases,
            description=spec.description,
        )
        existing.add(spec.name)
        existing.update(aliases)
