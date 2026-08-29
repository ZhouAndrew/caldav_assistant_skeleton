"""Human-facing Task/Event CRUD actions for the CLI.

This module is presentation/composition only.  It uses PromptKit through ``ctx.ui``
and the frozen Object API namespaces through ``ctx.tasks``/``ctx.events``.  It does
not access CalDAV XML, IPC details, SQLite, or duplicate Core validation rules.
"""
from __future__ import annotations

from typing import Any, Callable

from ...api.v1.errors import AmbiguousError, NotFoundError, ValidationError


_WORK_EVENT_CATEGORY = "caldav-assistant-work"


class CrudActions:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def _show(self, value: Any) -> None:
        show = getattr(self.ctx.ui, "show", None)
        if callable(show):
            show(value)

    def _choose(self, title: str, items: list[str]) -> str | None:
        choose = getattr(self.ctx.ui, "choose", None)
        if not callable(choose):
            raise ValidationError(f"{title} requires interactive UI")
        return choose(title, items)

    def _ask_text(self, prompt: str, **options: Any) -> str | None:
        ask = getattr(self.ctx.ui, "ask_text", None)
        if not callable(ask):
            raise ValidationError(f"{prompt} requires interactive UI")
        return ask(prompt, **options)

    def _ask_date(self, prompt: str) -> Any:
        ask = getattr(self.ctx.ui, "ask_date", None)
        if not callable(ask):
            raise ValidationError(f"{prompt} requires date input support")
        return ask(prompt)

    def _ask_datetime(self, prompt: str) -> Any:
        ask = getattr(self.ctx.ui, "ask_datetime", None)
        if not callable(ask):
            raise ValidationError(f"{prompt} requires date/time input support")
        return ask(prompt)

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
    def _parse_categories(text: str | None) -> list[str] | None:
        if text is None:
            return None
        return [item.strip() for item in text.split(",") if item.strip()]

    @staticmethod
    def _ordinary_event(value: Any) -> bool:
        return _WORK_EVENT_CATEGORY not in set(getattr(value, "categories", ()) or ())

    def _ordinary_events(self) -> list[Any]:
        return [
            item
            for item in (self.ctx.events.list() or ())
            if self._ordinary_event(item)
        ]

    def _task_target(self, parts: tuple[Any, ...]) -> Any:
        if not parts:
            choose_task = getattr(self.ctx.ui, "choose_task", None)
            if not callable(choose_task):
                raise ValidationError("Task selection requires interactive UI")
            return choose_task()
        return self.ctx.tasks.find(self._join(parts, label="Task"))

    def _event_target(self, parts: tuple[Any, ...]) -> Any:
        items = self._ordinary_events()
        if not parts:
            choose = getattr(self.ctx.ui, "choose", None)
            if not callable(choose):
                raise ValidationError("Event selection requires interactive UI")
            return choose(
                "Choose event",
                items,
                item_label=lambda item: self._summary(item),
            )

        query = self._join(parts, label="Event")
        needle = query.casefold()
        exact = [item for item in items if self._summary(item).casefold() == needle]
        matches = exact or [
            item for item in items if needle in self._summary(item).casefold()
        ]
        if not matches:
            raise NotFoundError(query)
        if len(matches) > 1:
            raise AmbiguousError(query)
        return matches[0]

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    def _task_create_fields(self) -> dict[str, Any] | None:
        fields: dict[str, Any] = {}
        timing = self._choose(
            "Task timing",
            ["No date", "Due date", "Planned start", "Planned start and due"],
        )
        if timing is None:
            return None
        if timing in {"Planned start", "Planned start and due"}:
            value = self._ask_date("Planned start")
            if value is None:
                return None
            fields["start"] = value
        if timing in {"Due date", "Planned start and due"}:
            value = self._ask_date("Due date")
            if value is None:
                return None
            fields["due"] = value

        while True:
            selected = self._choose(
                "Optional Task fields",
                ["Priority", "Description", "Categories", "Create"],
            )
            if selected is None:
                return None
            if selected == "Create":
                return fields
            if selected == "Priority":
                raw = self._ask_text("Priority (0-9)")
                if raw is None:
                    continue
                try:
                    priority = int(str(raw).strip())
                except ValueError as exc:
                    raise ValidationError("Priority must be an integer from 0 to 9") from exc
                if not 0 <= priority <= 9:
                    raise ValidationError("Priority must be an integer from 0 to 9")
                fields["priority"] = priority
            elif selected == "Description":
                value = self._ask_text("Description", allow_empty=True)
                if value is not None:
                    fields["description"] = value
            elif selected == "Categories":
                value = self._parse_categories(
                    self._ask_text("Categories (comma separated)", allow_empty=True)
                )
                if value is not None:
                    fields["categories"] = value

    def _event_create_fields(self) -> dict[str, Any] | None:
        fields: dict[str, Any] = {}
        timing = self._choose("Event time", ["All-day date", "Date/time"])
        if timing is None:
            return None
        ask_when: Callable[[str], Any] = (
            self._ask_date if timing == "All-day date" else self._ask_datetime
        )
        start = ask_when("Starts")
        if start is None:
            return None
        fields["start"] = start

        while True:
            selected = self._choose(
                "Optional Event fields",
                ["End", "Location", "Description", "Categories", "Create"],
            )
            if selected is None:
                return None
            if selected == "Create":
                return fields
            if selected == "End":
                value = ask_when("Ends")
                if value is not None:
                    fields["end"] = value
            elif selected == "Location":
                value = self._ask_text("Location", allow_empty=True)
                if value is not None:
                    fields["location"] = value
            elif selected == "Description":
                value = self._ask_text("Description", allow_empty=True)
                if value is not None:
                    fields["description"] = value
            elif selected == "Categories":
                value = self._parse_categories(
                    self._ask_text("Categories (comma separated)", allow_empty=True)
                )
                if value is not None:
                    fields["categories"] = value

    def add(self, *parts: Any) -> Any:
        kind: str | None = None
        title_parts: tuple[Any, ...] = ()
        if parts:
            first = str(parts[0]).strip().casefold()
            if first in {"task", "todo", "t"}:
                kind, title_parts = "Task", parts[1:]
            elif first in {"event", "calendar", "e"}:
                kind, title_parts = "Event", parts[1:]
            else:
                # A bare title is preserved, but Task/Event remains an explicit
                # selection rather than a hidden guess.
                title_parts = parts

        if kind is None:
            kind = self._choose("Add", ["Task", "Event"])
            if kind is None:
                return None

        if title_parts:
            title = self._join(title_parts, label=f"{kind} title")
        else:
            title = self._ask_text(f"{kind} title")
            if title is None:
                return None

        if kind == "Task":
            fields = self._task_create_fields()
            if fields is None:
                return None
            self._show(f"Create Task → {title}")
            return self.ctx.tasks.create(title, **fields)

        fields = self._event_create_fields()
        if fields is None:
            return None
        self._show(f"Create Event → {title}")
        return self.ctx.events.create(title, **fields)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def tasks(self, *parts: Any) -> None:
        if parts:
            raise ValidationError("tasks does not take arguments")
        items = list(self.ctx.tasks.list() or ())
        self._show(f"Tasks · {len(items)}")
        if not items:
            self._show("(none)")
            return None
        for index, item in enumerate(items, 1):
            self._show(f"{index:>3}. {self._summary(item)}")
        return None

    def events(self, *parts: Any) -> None:
        if parts:
            raise ValidationError("events does not take arguments")
        items = self._ordinary_events()
        self._show(f"Events · {len(items)}")
        if not items:
            self._show("(none)")
            return None
        for index, item in enumerate(items, 1):
            self._show(f"{index:>3}. {self._summary(item)}")
        return None

    # ------------------------------------------------------------------
    # Update Event (Task update remains the existing `edit` command)
    # ------------------------------------------------------------------
    def edit_event(self, *parts: Any) -> Any:
        event = self._event_target(parts)
        if event is None:
            return None

        selected = self._choose(
            "Modify Event",
            ["Title", "Start", "End", "Location", "Description", "Categories"],
        )
        if selected is None:
            return None

        changes: dict[str, Any] = {}
        if selected == "Title":
            value = self._ask_text("New title")
            if value is None:
                return None
            changes["summary"] = value
        elif selected in {"Start", "End"}:
            timing = self._choose(f"{selected} type", ["All-day date", "Date/time"])
            if timing is None:
                return None
            ask_when = self._ask_date if timing == "All-day date" else self._ask_datetime
            value = ask_when(selected)
            if value is None:
                return None
            changes[selected.casefold()] = value
        elif selected == "Location":
            value = self._ask_text("Location", allow_empty=True)
            if value is None:
                return None
            changes["location"] = value
        elif selected == "Description":
            value = self._ask_text("Description", allow_empty=True)
            if value is None:
                return None
            changes["description"] = value
        elif selected == "Categories":
            value = self._parse_categories(
                self._ask_text("Categories (comma separated)", allow_empty=True)
            )
            if value is None:
                return None
            changes["categories"] = value

        self._show(f"Edit Event → {self._summary(event)}; {selected}")
        return self.ctx.events.update(event, **changes)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def _confirm_delete(self, kind: str, value: Any) -> bool:
        confirm = getattr(self.ctx.ui, "confirm", None)
        if not callable(confirm):
            raise ValidationError("Delete requires interactive confirmation")
        self._show(
            f"Delete {kind} → {self._summary(value)}\n"
            "This removes the CalDAV object. The next `undo` can restore it."
        )
        return bool(confirm("Continue?", default=False))

    def _reject_active_task_delete(self, task: Any) -> None:
        session = getattr(self.ctx, "session", None)
        getter = getattr(session, "current_task_id", None)
        if not callable(getter):
            return
        current_id = getter()
        task_id = str(getattr(task, "id", "") or "")
        if current_id and str(current_id) == task_id:
            raise ValidationError(
                "The current Task cannot be deleted while work is active. "
                "Pause or complete it first so no open work interval is orphaned."
            )

    def remove(self, *parts: Any) -> Any:
        kind: str | None = None
        target_parts: tuple[Any, ...] = ()
        if parts:
            first = str(parts[0]).strip().casefold()
            if first in {"task", "todo", "t"}:
                kind, target_parts = "Task", parts[1:]
            elif first in {"event", "calendar", "e"}:
                kind, target_parts = "Event", parts[1:]
            else:
                raise ValidationError("remove requires `task` or `event` before a name")

        if kind is None:
            kind = self._choose("Remove", ["Task", "Event"])
            if kind is None:
                return None

        target = (
            self._task_target(target_parts)
            if kind == "Task"
            else self._event_target(target_parts)
        )
        if target is None:
            return None
        if kind == "Task":
            self._reject_active_task_delete(target)
        if not self._confirm_delete(kind, target):
            return None

        if kind == "Task":
            return self.ctx.tasks.delete(target)
        return self.ctx.events.delete(target)


def register_crud_cli_commands(commands: Any, ctx: Any) -> CrudActions:
    actions = CrudActions(ctx)
    specs = (
        ("add", actions.add, ("new",), "Create a Task or Event through a guided flow."),
        ("tasks", actions.tasks, (), "List Tasks."),
        ("events", actions.events, (), "List Events."),
        ("edit-event", actions.edit_event, ("event-edit",), "Interactively edit an Event."),
        ("remove", actions.remove, ("delete",), "Delete a Task or Event with confirmation."),
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


__all__ = ["CrudActions", "register_crud_cli_commands"]
