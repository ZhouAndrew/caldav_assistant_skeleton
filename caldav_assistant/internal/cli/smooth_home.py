"""Keep the zero-learning home menu in one coherent interaction mode.

The conversation client supports both a numbered guided menu and direct canonical
commands. Number input at the top-level prompt follows the same visible home menu,
instead of being misrouted to CommandRegistry as an unsupported command.
"""
from __future__ import annotations

from typing import Any


_HOME_TITLE = "What do you want to do?"
_LEAVE_HOME = "Stay in console"


def _stable_home_items(items: Any) -> tuple[Any, ...]:
    values = list(items)
    if len(values) < 2:
        return tuple(values)

    def primary(value: Any) -> bool:
        text = str(value)
        return (
            text.startswith("Return to Waiting Mode")
            or text.startswith("Start recommended Task")
            or text == "Choose a Task and start"
        )

    primary_index = next((i for i, value in enumerate(values) if primary(value)), None)
    upcoming_index = next(
        (i for i, value in enumerate(values) if str(value).startswith("Upcoming —")),
        None,
    )
    if primary_index is None or upcoming_index is None:
        return tuple(values)

    first = values[primary_index]
    second = values[upcoming_index]
    remainder = [
        value
        for i, value in enumerate(values)
        if i not in {primary_index, upcoming_index}
    ]
    return (first, second, *remainder)


_INVALIDATES_HOME_SNAPSHOT = frozenset(
    {
        "Task / Event management",
        "Upcoming settings",
        "Settings and setup",
    }
)


def _replace_instance_attribute(obj: Any, name: str, value: Any):
    values = getattr(obj, "__dict__", None)
    had_instance_value = isinstance(values, dict) and name in values
    previous_instance_value = values.get(name) if had_instance_value else None
    setattr(obj, name, value)

    def restore() -> None:
        if had_instance_value:
            setattr(obj, name, previous_instance_value)
            return
        try:
            delattr(obj, name)
        except AttributeError:
            pass

    return restore


def install(module: Any) -> None:
    """Keep menu mode stable and make bare top-level numbers select that menu."""
    if bool(getattr(module, "_smooth_home_installed", False)):
        return

    conversation = module.conversation
    original_home_menu = conversation._home_menu
    # Small public/unit-test compositions may exercise only the home-menu brick and
    # intentionally omit the command executor. Preserve that replacement contract;
    # numeric console support is installed only when the real executor exists.
    original_execute_user = getattr(module, "_execute_user", None)

    def persistent_home_menu(app: Any, snapshot: Any):
        ui = getattr(getattr(app, "ctx", None), "ui", None)
        choose = getattr(ui, "choose", None)
        if not callable(choose):
            return original_home_menu(app, snapshot)

        active_snapshot = snapshot

        while True:
            selection: dict[str, Any] = {"seen": False, "value": None}
            refreshed: dict[str, Any] = {"value": active_snapshot}
            bound_choose = getattr(ui, "choose")

            def recording_choose(title: str, items: Any, **kwargs: Any):
                visible_items = (
                    _stable_home_items(items)
                    if str(title) == _HOME_TITLE
                    else items
                )
                value = bound_choose(title, visible_items, **kwargs)
                if str(title) == _HOME_TITLE and not selection["seen"]:
                    selection["seen"] = True
                    selection["value"] = value
                return value

            visible_now = conversation._visible_call

            def tracking_visible_call(
                current_app: Any,
                label: str,
                fn: Any,
                *args: Any,
                **kwargs: Any,
            ):
                value = visible_now(current_app, label, fn, *args, **kwargs)
                if isinstance(value, conversation.StartupSnapshot):
                    refreshed["value"] = value
                return value

            restore_choose = _replace_instance_attribute(ui, "choose", recording_choose)
            conversation._visible_call = tracking_visible_call
            try:
                action = original_home_menu(app, active_snapshot)
            finally:
                conversation._visible_call = visible_now
                restore_choose()

            active_snapshot = refreshed["value"]

            if action != "console":
                return action
            if not selection["seen"]:
                return action

            selected = selection["value"]
            if selected is None or str(selected) == _LEAVE_HOME:
                return "console"

            if str(selected) in _INVALIDATES_HOME_SNAPSHOT:
                conversation._show(
                    app,
                    "Returned to the command console because Task/Event or setup state may have changed.",
                )
                return "console"

    conversation._home_menu = persistent_home_menu

    if callable(original_execute_user):
        def execute_user(app: Any, parsed: Any, *, paginate: bool = True):
            raw = str(getattr(parsed, "raw", "") or "").strip()
            if not raw.isdigit() or tuple(getattr(parsed, "args", ()) or ()):
                return original_execute_user(app, parsed, paginate=paginate)

            number = int(raw)
            if number == 0:
                return 0, False

            ui = getattr(getattr(app, "ctx", None), "ui", None)
            choose = getattr(ui, "choose", None)
            if not callable(choose):
                return original_execute_user(app, parsed, paginate=paginate)

            used = False
            bound_choose = choose

            def seeded_choose(title: str, items: Any, **kwargs: Any):
                nonlocal used
                if str(title) == _HOME_TITLE and not used:
                    used = True
                    visible = _stable_home_items(items)
                    if 1 <= number <= len(visible):
                        return visible[number - 1]
                    conversation._show(
                        app,
                        f"Invalid home-menu number: {number}. Choose one of the visible numbers.",
                    )
                return bound_choose(title, items, **kwargs)

            restore_choose = _replace_instance_attribute(ui, "choose", seeded_choose)
            try:
                action = conversation._home_menu(app, None)
            finally:
                restore_choose()

            if action == "exit":
                return 0, True
            if action == "wait":
                waiting = getattr(module, "_waiting_mode", None)
                if callable(waiting):
                    follow = waiting(app)
                    return 0, follow == "exit"
            return 0, False

        module._execute_user = execute_user

    module._smooth_home_installed = True


__all__ = ["install"]
