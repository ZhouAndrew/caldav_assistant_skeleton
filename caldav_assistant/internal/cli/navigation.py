"""Log-history queries and real hierarchical CLI navigation.

This module is presentation/composition only. Direct commands remain canonical entry
points; ``menu`` declares a navigation tree and dispatches executable leaves to the
same CommandService handlers used by the normal REPL.

The navigation tree has an explicit stack. Therefore a submenu has a parent, ``0``
returns exactly one level, and the title shows the current path. Selecting an action
leaf deliberately leaves navigation after dispatch so result rendering remains owned
by the ordinary CLI path rather than a second modal shell.

Navigation is also non-modal: at any level, production terminal users may type a
normal CLI command. The shared Menu passes unmatched text to ``push_line`` and this
module exits the navigation stack; the normal REPL then parses that exact line.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Callable

from ...api.v1.errors import ValidationError


_RELEASED_TO_REPL = object()


@dataclass(frozen=True, slots=True)
class NavigationCommand:
    """A leaf in the navigation tree that delegates to one canonical command."""

    label: str
    command: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NavigationMenu:
    """A real parent/child node; business behavior never lives here."""

    label: str
    children: tuple[Any, ...]


class NavigationActions:
    """Human-facing history bricks plus a stack-based goal navigation tree."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    @staticmethod
    def _summary(value: Any) -> str:
        text = getattr(value, "summary", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        value_id = getattr(value, "id", None)
        return str(value_id or value)

    @staticmethod
    def _join(parts: tuple[Any, ...], *, label: str) -> str:
        if not parts or not all(isinstance(part, str) for part in parts):
            raise ValidationError(f"{label} must be text")
        value = " ".join(part.strip() for part in parts if part.strip()).strip()
        if not value:
            raise ValidationError(f"{label} must not be empty")
        return value

    def _release_to_repl(self, raw: str) -> Any:
        ui = getattr(self.ctx, "ui", None)
        io = getattr(ui, "io", None)
        push_line = getattr(io, "push_line", None)
        if not callable(push_line):
            raise ValidationError("This client cannot hand a command line back to the REPL")
        push_line(raw)
        return _RELEASED_TO_REPL

    def _choose(
        self,
        title: str,
        items: tuple[str, ...],
        *,
        back_label: str = "Back",
    ) -> Any:
        """Use the shared PromptKit/Menu instead of implementing another menu loop."""
        ui = getattr(self.ctx, "ui", None)
        choose = getattr(ui, "choose", None)
        if not callable(choose):
            raise ValidationError(f"{title} requires interactive UI")

        io = getattr(ui, "io", None)
        push_line = getattr(io, "push_line", None)
        options: dict[str, Any] = {
            "searchable": False,
            "back_label": back_label,
            "help_text": (
                "Choose by number. 0 goes back one level. Commands are optional "
                "shortcuts; in the terminal you may also type a normal command here."
            ),
        }
        if callable(push_line):
            options["on_unmatched"] = self._release_to_repl
        return choose(title, items, **options)

    def _run(self, name: str, *args: Any) -> Any:
        """Dispatch through the same registry used by direct CLI commands."""
        return self.ctx.commands.run(name, *args)

    @staticmethod
    def _stamp(value: Any) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.astimezone()
            return value.astimezone().isoformat(timespec="seconds")
        return str(value or "—")

    @staticmethod
    def _metadata(value: Any) -> str:
        if not value:
            return ""
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return repr(value)

    def _activity_text(self, items: Any, *, title: str) -> str:
        values = list(items or ())
        lines = [title, f"Entries: {len(values)}"]
        if not values:
            lines.append("(none)")
            return "\n".join(lines)

        for index, item in enumerate(values, 1):
            timestamp = self._stamp(getattr(item, "timestamp", None))
            action = str(getattr(item, "action", "") or "unknown")
            object_id = str(getattr(item, "object_id", "") or "").strip()
            line = f"{index:>3}. {timestamp}  {action}"
            if object_id:
                line += f"  object={object_id}"
            lines.append(line)
            metadata = self._metadata(getattr(item, "metadata", None))
            if metadata:
                lines.append(f"     metadata={metadata}")
        return "\n".join(lines)

    def _history_today(self) -> str:
        return self._activity_text(
            self.ctx.activity.today(),
            title="Activity Journal · today · local SQLite",
        )

    def _history_task(self, parts: tuple[Any, ...]) -> str | None:
        if parts:
            task = self.ctx.tasks.find(self._join(parts, label="Task"))
        else:
            chooser = getattr(self.ctx.ui, "choose_task", None)
            if not callable(chooser):
                raise ValidationError("Task history requires interactive Task selection")
            task = chooser(title="Task history")
        if task is None:
            return None
        title = f"Activity Journal · Task · {self._summary(task)}"
        return self._activity_text(self.ctx.activity.for_task(task), title=title)

    def _history_wordpress(self) -> str:
        reader = getattr(self.ctx.wordpress, "_daily_log", None)
        if not callable(reader):
            raise ValidationError(
                "This runtime cannot query the real WordPress daily-log post; restart/update the background service"
            )
        item = reader()
        if item is None:
            return "WordPress daily log · today\nNo matching WordPress post exists."
        if not isinstance(item, dict):
            raise ValidationError("WordPress daily-log query returned invalid data")
        post_id = item.get("id", "—")
        title = item.get("title", "—")
        content = str(item.get("content", "") or "")
        return "\n".join(
            [
                "WordPress daily log · today · REAL post_content",
                f"Post ID: {post_id}",
                f"Title: {title}",
                "Content:",
                content or "(empty)",
            ]
        )

    def _history_pending(self) -> str:
        values = list(self.ctx.wordpress.pending() or ())
        lines = ["WordPress Outbox · pending", f"Entries: {len(values)}"]
        if not values:
            lines.append("(none)")
            return "\n".join(lines)

        for item in values:
            if not isinstance(item, dict):
                lines.append(f"- {item!r}")
                continue
            item_id = item.get("id", "—")
            attempts = item.get("attempts", 0)
            created_at = item.get("created_at", "—")
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            operation = payload.get("operation", "unknown")
            request_id = payload.get("request_id", "—")
            lines.append(
                f"- id={item_id} operation={operation} attempts={attempts} created={created_at} request={request_id}"
            )
            error = item.get("last_error")
            if error:
                lines.append(f"  last_error={error}")
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            text = args.get("text")
            if text:
                lines.append(f"  text={text}")
        return "\n".join(lines)

    def _history_menu(self) -> Any:
        selected = self._choose(
            "History",
            (
                "Activity today",
                "Task history",
                "WordPress today (real post)",
                "Pending WordPress uploads",
            ),
        )
        if selected is None or selected is _RELEASED_TO_REPL:
            return None
        actions: dict[str, Callable[[], Any]] = {
            "Activity today": lambda: self.history("today"),
            "Task history": lambda: self.history("task"),
            "WordPress today (real post)": lambda: self.history("wordpress"),
            "Pending WordPress uploads": lambda: self.history("pending"),
        }
        return actions[selected]()

    def history(self, *parts: Any) -> Any:
        """Query local Activity, Task history, real WordPress content, or Outbox."""
        if not parts:
            return self._history_menu()
        if not all(isinstance(part, str) for part in parts):
            raise ValidationError("history arguments must be text")

        kind = parts[0].strip().casefold()
        rest = parts[1:]
        if kind in {"today", "activity", "local", "sqlite"}:
            if rest:
                raise ValidationError("history today does not take extra arguments")
            return self._history_today()
        if kind in {"task", "todo"}:
            return self._history_task(rest)
        if kind in {"wordpress", "wp", "remote"}:
            if rest and tuple(str(item).strip().casefold() for item in rest) != ("today",):
                raise ValidationError("history wordpress only supports today's daily log")
            return self._history_wordpress()
        if kind in {"pending", "outbox"}:
            if rest:
                raise ValidationError("history pending does not take extra arguments")
            return self._history_pending()
        raise ValidationError(
            "history expects: today | task [name] | wordpress | pending"
        )

    # ------------------------------------------------------------------
    # Real hierarchy: declarative tree + navigation stack + CommandService leaves.
    # ------------------------------------------------------------------
    @staticmethod
    def _navigation_tree() -> NavigationMenu:
        tasks = NavigationMenu(
            "Tasks",
            (
                NavigationCommand("List Tasks", "tasks"),
                NavigationCommand("Edit Task", "edit"),
                NavigationCommand("Complete Task", "done"),
            ),
        )
        events = NavigationMenu(
            "Events",
            (
                NavigationCommand("List Events", "events"),
                NavigationCommand("Edit Event", "edit-event"),
            ),
        )
        return NavigationMenu(
            "CalDAV Assistant",
            (
                NavigationMenu(
                    "Agenda",
                    (
                        NavigationCommand("Today", "today"),
                        NavigationCommand("Next", "next"),
                        NavigationCommand("Current work", "current"),
                    ),
                ),
                NavigationMenu(
                    "Work",
                    (
                        NavigationCommand("Start recommended task", "start"),
                        NavigationCommand("Pause current task", "pause"),
                        NavigationCommand("Resume paused task", "resume"),
                        NavigationCommand("Complete task", "done"),
                    ),
                ),
                NavigationMenu(
                    "Logs",
                    (
                        NavigationCommand("Write log", "log"),
                        NavigationCommand("Activity today", "history", ("today",)),
                        NavigationCommand("Task history", "history", ("task",)),
                        NavigationCommand(
                            "WordPress today (real post)",
                            "history",
                            ("wordpress",),
                        ),
                        NavigationCommand(
                            "Pending WordPress uploads",
                            "history",
                            ("pending",),
                        ),
                    ),
                ),
                NavigationMenu(
                    "Manage",
                    (
                        NavigationCommand("Add Task/Event", "add"),
                        tasks,
                        events,
                        NavigationCommand("Remove Task/Event", "remove"),
                    ),
                ),
                NavigationCommand("Settings & setup", "settings"),
                NavigationCommand("Help", "help"),
            ),
        )

    @staticmethod
    def _path_title(stack: list[NavigationMenu]) -> str:
        return " > ".join(node.label for node in stack)

    def menu(self, *parts: Any) -> Any:
        """Navigate a real parent/child tree, then dispatch one canonical leaf."""
        if parts:
            raise ValidationError("menu does not take arguments; use direct commands for scripting")

        root = self._navigation_tree()
        stack: list[NavigationMenu] = [root]

        while stack:
            node = stack[-1]
            labels = tuple(child.label for child in node.children)
            if len(stack) == 1:
                back_label = "Leave menu"
            else:
                back_label = f"Back to {stack[-2].label}"

            selected = self._choose(
                self._path_title(stack),
                labels,
                back_label=back_label,
            )
            if selected is _RELEASED_TO_REPL:
                return None
            if selected is None:
                if len(stack) == 1:
                    return None
                stack.pop()
                continue

            child = next((item for item in node.children if item.label == selected), None)
            if child is None:
                raise ValidationError(f"Navigation item disappeared: {selected}")
            if isinstance(child, NavigationMenu):
                stack.append(child)
                continue
            if isinstance(child, NavigationCommand):
                return self._run(child.command, *child.args)
            raise ValidationError(f"Unsupported navigation node: {type(child).__name__}")

        return None


def register_navigation_cli_commands(commands: Any, ctx: Any) -> NavigationActions:
    """Register navigation without replacing any existing direct command."""
    actions = NavigationActions(ctx)
    specs = (
        (
            "history",
            actions.history,
            ("logs", "journal"),
            "Query local Activity, Task history, the real WordPress daily post, or pending uploads.",
        ),
        (
            "menu",
            actions.menu,
            ("m",),
            "Open guided hierarchical navigation; numbers work without learning commands.",
        ),
    )
    existing = set(commands.names(include_aliases=True))
    for name, handler, aliases, description in specs:
        if name in existing:
            continue
        safe_aliases = tuple(alias for alias in aliases if alias not in existing)
        commands.register_builtin(
            name,
            handler,
            aliases=safe_aliases,
            description=description,
        )
        existing.add(name)
        existing.update(safe_aliases)
    return actions


__all__ = [
    "NavigationActions",
    "NavigationCommand",
    "NavigationMenu",
    "register_navigation_cli_commands",
]
