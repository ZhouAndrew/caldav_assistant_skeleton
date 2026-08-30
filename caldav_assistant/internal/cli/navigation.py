"""Log-history queries and optional multi-level CLI navigation.

This module is presentation/composition only. Direct commands remain the canonical
entry points; ``menu`` simply dispatches to those same CommandService handlers.
Activity queries use the public Activity namespace. Reading the real WordPress daily
post uses a deliberately private CLI observability method so the frozen public v1
WordPress API does not need to grow transport-specific query semantics.

Navigation is intentionally *not* a second CLI mode. At every navigation level a
user may type any ordinary command. Production StdConsoleIO pushes that raw line
back to the normal REPL, so aliases, numbered references, parsing, rendering and
error handling stay exactly the same as at the top-level ``>`` prompt.

A submenu ``0/back`` means *one level up*. It must not silently terminate the whole
navigation command. Ordinary command handoff is kept distinct from Back so a command
typed inside a submenu exits navigation and is executed by the normal REPL.
"""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Callable

from ...api.v1.errors import ValidationError


class _NavigationSignal:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<{self.name}>"


_BACK_ONE_LEVEL = _NavigationSignal("BACK_ONE_LEVEL")
_HANDOFF_TO_REPL = _NavigationSignal("HANDOFF_TO_REPL")


class NavigationActions:
    """Small human-facing bricks for history queries and nested menus."""

    _BACK = frozenset({"0", "back", "b", "q", "quit", "cancel", "c"})
    _HELP = frozenset({"?", "help", "h"})

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

    @staticmethod
    def _exact_label(items: tuple[str, ...], raw: str) -> str | None:
        needle = raw.strip().casefold()
        matches = [item for item in items if item.strip().casefold() == needle]
        return matches[0] if len(matches) == 1 else None

    def _choose(self, title: str, items: tuple[str, ...]) -> str | _NavigationSignal:
        """Choose one navigation item without trapping ordinary CLI commands.

        ``_BACK_ONE_LEVEL`` and ``_HANDOFF_TO_REPL`` are deliberately distinct.
        Without that distinction a submenu cannot know whether ``0`` should return to
        its parent or whether a normal CLI command was handed back to the REPL.
        """
        ui = getattr(self.ctx, "ui", None)
        io = getattr(ui, "io", None)
        reader = getattr(io, "read", None)
        writer = getattr(io, "write", None)
        push_line = getattr(io, "push_line", None)

        if not (callable(reader) and callable(writer) and callable(push_line)):
            choose = getattr(ui, "choose", None)
            if not callable(choose):
                raise ValidationError(f"{title} requires interactive UI")
            selected = choose(title, items)
            return _BACK_ONE_LEVEL if selected is None else str(selected)

        values = tuple(str(item) for item in items)
        while True:
            writer(title)
            for index, label in enumerate(values, 1):
                writer(f"{index}. {label}")
            writer("0. Back")
            writer("Tip: type any normal CLI command here to run it and leave the menu.")
            raw = str(reader("> ") or "").strip()
            token = raw.casefold()

            if token in self._BACK:
                return _BACK_ONE_LEVEL
            if token in self._HELP:
                writer(
                    "Choose by number or exact label. 0/back returns one level. "
                    "Any other command line is handed to the normal CLI."
                )
                continue

            exact = self._exact_label(values, raw)
            if exact is not None:
                return exact

            try:
                index = int(raw)
            except ValueError:
                index = -1
            if 1 <= index <= len(values):
                return values[index - 1]
            if raw.isascii() and raw.isdigit():
                writer(
                    f"Choose 1-{len(values)}, 0 to go back, or type a normal CLI command."
                )
                continue

            if not raw:
                continue
            push_line(raw)
            return _HANDOFF_TO_REPL

    @staticmethod
    def _is_signal(value: Any) -> bool:
        return value is _BACK_ONE_LEVEL or value is _HANDOFF_TO_REPL

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
            "Logs / History",
            (
                "Activity today",
                "Task history",
                "WordPress today (real post)",
                "Pending WordPress uploads",
            ),
        )
        if self._is_signal(selected):
            return None
        actions: dict[str, Callable[[], Any]] = {
            "Activity today": lambda: self.history("today"),
            "Task history": lambda: self.history("task"),
            "WordPress today (real post)": lambda: self.history("wordpress"),
            "Pending WordPress uploads": lambda: self.history("pending"),
        }
        return actions[str(selected)]()

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
    # Multi-level menu: dispatch only, never duplicate command behavior.
    # ------------------------------------------------------------------
    def _agenda_menu(self) -> Any:
        selected = self._choose("Agenda", ("Today", "Next", "Current work"))
        if self._is_signal(selected):
            return selected
        return {
            "Today": lambda: self._run("today"),
            "Next": lambda: self._run("next"),
            "Current work": lambda: self._run("current"),
        }[str(selected)]()

    def _work_menu(self) -> Any:
        selected = self._choose(
            "Work",
            ("Start recommended task", "Pause current task", "Resume paused task", "Complete task"),
        )
        if self._is_signal(selected):
            return selected
        return {
            "Start recommended task": lambda: self._run("start"),
            "Pause current task": lambda: self._run("pause"),
            "Resume paused task": lambda: self._run("resume"),
            "Complete task": lambda: self._run("done"),
        }[str(selected)]()

    def _logs_menu(self) -> Any:
        selected = self._choose(
            "Logs",
            (
                "Write log",
                "Activity today",
                "Task history",
                "WordPress today (real post)",
                "Pending WordPress uploads",
            ),
        )
        if self._is_signal(selected):
            return selected
        return {
            "Write log": lambda: self._run("log"),
            "Activity today": lambda: self._run("history", "today"),
            "Task history": lambda: self._run("history", "task"),
            "WordPress today (real post)": lambda: self._run("history", "wordpress"),
            "Pending WordPress uploads": lambda: self._run("history", "pending"),
        }[str(selected)]()

    def _manage_menu(self) -> Any:
        selected = self._choose(
            "Manage",
            ("Add Task/Event", "List Tasks", "List Events", "Edit Task", "Edit Event", "Remove Task/Event"),
        )
        if self._is_signal(selected):
            return selected
        return {
            "Add Task/Event": lambda: self._run("add"),
            "List Tasks": lambda: self._run("tasks"),
            "List Events": lambda: self._run("events"),
            "Edit Task": lambda: self._run("edit"),
            "Edit Event": lambda: self._run("edit-event"),
            "Remove Task/Event": lambda: self._run("remove"),
        }[str(selected)]()

    def menu(self, *parts: Any) -> Any:
        if parts:
            raise ValidationError("menu does not take arguments; use direct commands for scripting")

        root_actions: dict[str, Callable[[], Any]] = {
            "Agenda": self._agenda_menu,
            "Work": self._work_menu,
            "Logs": self._logs_menu,
            "Manage": self._manage_menu,
            "Help": lambda: self._run("help"),
        }
        while True:
            selected = self._choose(
                "CalDAV Assistant",
                ("Agenda", "Work", "Logs", "Manage", "Help"),
            )
            if selected is _BACK_ONE_LEVEL or selected is _HANDOFF_TO_REPL:
                return None

            outcome = root_actions[str(selected)]()
            if outcome is _BACK_ONE_LEVEL:
                # Child 0/back returns to the root menu, not the top-level REPL.
                continue
            if outcome is _HANDOFF_TO_REPL:
                # A normal command typed in a child menu was pushed back to REPL.
                return None
            return outcome


def register_navigation_cli_commands(commands: Any, ctx: Any) -> NavigationActions:
    """Register optional navigation without replacing any existing direct command."""
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
            "Open optional navigation; numbers and ordinary CLI commands work side by side.",
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


__all__ = ["NavigationActions", "register_navigation_cli_commands"]
