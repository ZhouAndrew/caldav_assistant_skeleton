"""Human-facing Task/Event CRUD actions for the CLI.

This module is presentation/composition only. It uses PromptKit through ``ctx.ui``
and the frozen Object API namespaces through ``ctx.tasks``/``ctx.events``. It does
not access CalDAV XML, IPC details, SQLite, or duplicate Core validation rules.

Any numbered Task/Event list shown by this module is also recorded in Session state.
A visible number is therefore an actionable reference, not decorative output.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ...api.v1.errors import AmbiguousError, NotFoundError, ValidationError
from ..prompts.pickers import task_is_overdue, task_matches_date
from ..settings.keys import CALDAV_TASK_COLLECTION_URL, TASK_DEFAULT_VIEW


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

    def _remember_numbered_items(self, items: list[Any]) -> None:
        session = getattr(self.ctx, "session", None)
        if session is None:
            return
        try:
            session.last_items = list(items)
            session.current_selection = None
        except Exception:
            # Small test/extension Session implementations may be read-only. The
            # list command must remain usable even when contextual references are
            # unavailable.
            return

    def _task_target(self, parts: tuple[Any, ...]) -> Any:
        if not parts:
            choose_task = getattr(self.ctx.ui, "choose_task", None)
            if not callable(choose_task):
                raise ValidationError("Task selection requires interactive UI")
            return choose_task()
        if len(parts) == 1 and not isinstance(parts[0], str):
            return parts[0]
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
        if len(parts) == 1 and not isinstance(parts[0], str):
            event = parts[0]
            if not self._ordinary_event(event):
                raise ValidationError("Internal work-session Events are not editable here")
            return event

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
    @staticmethod
    def _collection_value(item: Any, key: str) -> Any:
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    @classmethod
    def _collection_components(cls, item: Any) -> tuple[str, ...]:
        value = cls._collection_value(item, "components") or ()
        if isinstance(value, str):
            value = (value,)
        return tuple(str(part).strip().upper() for part in value if str(part).strip())

    @classmethod
    def _collection_name(cls, item: Any) -> str:
        value = cls._collection_value(item, "name")
        return str(value).strip() if value else str(cls._collection_value(item, "url") or "Task collection")

    @classmethod
    def _collection_url(cls, item: Any) -> str | None:
        value = cls._collection_value(item, "url")
        clean = str(value).strip() if value is not None else ""
        return clean or None

    def _ensure_default_task_collection(self) -> bool:
        """Guide first Task creation without inventing another collection system."""
        settings = getattr(self.ctx, "settings", None)
        getter = getattr(settings, "get", None)
        setter = getattr(settings, "set", None)
        collections = getattr(settings, "caldav_collections", None)
        if not (callable(getter) and callable(setter) and callable(collections)):
            return True
        if getter(CALDAV_TASK_COLLECTION_URL, None):
            return True

        discovered = list(collections() or ())
        compatible = [
            item
            for item in discovered
            if "VTODO" in self._collection_components(item) and self._collection_url(item)
        ]
        if not compatible:
            # Preserve the existing Core error path when discovery itself cannot
            # identify a Task collection; this helper is guidance, not a new Core.
            return True

        if len(compatible) == 1:
            selected = compatible[0]
            setter(CALDAV_TASK_COLLECTION_URL, self._collection_url(selected))
            self._show(
                f"✓ Default task collection: {self._collection_name(selected)} "
                "(the only compatible VTODO collection)."
            )
            self._show("Undo later with: settings reset caldav.task_collection_url")
            return True

        labels = [self._collection_name(item) for item in compatible]
        selected_label = self._choose(
            "Where should new Tasks be saved by default?",
            labels + ["Not now"],
        )
        if selected_label is None or selected_label == "Not now":
            self._show("Task creation cancelled; no default task collection was changed.")
            return False
        selected = compatible[labels.index(selected_label)]
        setter(CALDAV_TASK_COLLECTION_URL, self._collection_url(selected))
        self._show(f"✓ Default task collection: {self._collection_name(selected)}")

        decision = self._choose(
            "Default saved. What next?",
            ["Continue", "Undo", "Modify settings"],
        )
        if decision == "Undo":
            setter(CALDAV_TASK_COLLECTION_URL, None)
            self._show("✓ Default task collection restored to Not configured.")
            return False
        if decision == "Modify settings":
            runner = getattr(getattr(self.ctx, "commands", None), "run", None)
            if callable(runner):
                runner("settings", "tasks")
            else:
                self._show("Open settings → CalDAV → Collection roles.")
            if not getter(CALDAV_TASK_COLLECTION_URL, None):
                self._show("Task creation cancelled because no default task collection is configured.")
                return False
        return True

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
            if not self._ensure_default_task_collection():
                return None
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
    @staticmethod
    def _task_is_completed(item: Any) -> bool:
        return bool(getattr(item, "completed", False)) or str(
            getattr(item, "status", "") or ""
        ).strip().upper() == "COMPLETED"

    def _task_view(self, parts: tuple[Any, ...]) -> str:
        aliases = {"active": "incomplete", "unfinished": "incomplete", "done": "completed"}
        allowed = {"incomplete", "today", "overdue", "completed", "all"}
        if len(parts) > 1:
            raise ValidationError("tasks takes at most one view: incomplete, today, overdue, completed, or all")
        if parts:
            view = aliases.get(str(parts[0]).strip().casefold(), str(parts[0]).strip().casefold())
        else:
            settings = getattr(self.ctx, "settings", None)
            getter = getattr(settings, "get", None)
            configured = getter(TASK_DEFAULT_VIEW, "incomplete") if callable(getter) else "incomplete"
            view = aliases.get(str(configured).strip().casefold(), str(configured).strip().casefold())
        if view not in allowed:
            raise ValidationError("Unknown Task view. Use incomplete, today, overdue, completed, or all")
        return view

    def _tasks_for_view(self, view: str) -> list[Any]:
        if view == "all":
            return list(self.ctx.tasks.list() or ())
        if view == "completed":
            return [item for item in (self.ctx.tasks.list() or ()) if self._task_is_completed(item)]

        try:
            items = list(self.ctx.tasks.list(actionable=True) or ())
        except TypeError:
            # Compatibility with older/lightweight TasksAPI doubles. Production v1
            # accepts filters; keep the CLI graceful without changing list() defaults.
            items = [
                item
                for item in (self.ctx.tasks.list() or ())
                if not self._task_is_completed(item)
                and str(getattr(item, "status", "") or "").strip().upper() != "CANCELLED"
            ]
        today = datetime.now().astimezone().date()
        if view == "today":
            return [item for item in items if task_matches_date(item, today)]
        if view == "overdue":
            return [item for item in items if task_is_overdue(item, today)]
        return items

    def tasks(self, *parts: Any) -> None:
        view = self._task_view(parts)
        items = self._tasks_for_view(view)
        self._remember_numbered_items(items)
        self._show(f"Tasks · {view.title()} · {len(items)}")
        if not items:
            self._show("(none)")
            if view == "incomplete":
                history = [
                    item
                    for item in (self.ctx.tasks.list() or ())
                    if self._task_is_completed(item)
                    or str(getattr(item, "status", "") or "").strip().upper() == "CANCELLED"
                ]
                if history:
                    self._show(f"{len(history)} completed/cancelled Task(s) remain available in history.")
                self._show("Next: `tasks all` to inspect history, or `add task` to create a Task.")
            return None
        for index, item in enumerate(items, 1):
            self._show(f"{index:>3}. {self._summary(item)}")
        self._show("Views: `tasks incomplete` · `tasks today` · `tasks overdue` · `tasks completed` · `tasks all`")
        self._show("Numbers are active references for Task commands, e.g. `edit 3`, `start 3`, `done 3`.")
        return None

    def events(self, *parts: Any) -> None:
        if parts:
            raise ValidationError("events does not take arguments")
        items = self._ordinary_events()
        self._remember_numbered_items(items)
        self._show(f"Events · {len(items)}")
        if not items:
            self._show("(none)")
            return None
        for index, item in enumerate(items, 1):
            self._show(f"{index:>3}. {self._summary(item)}")
        self._show("Numbers are active references for Event commands, e.g. `edit-event 3`, `remove event 3`.")
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
