"""Keep the zero-learning home menu in one coherent interaction mode.

The conversation client intentionally supports both a numbered guided menu and direct
canonical commands.  A guided-menu selection must therefore not silently switch the
terminal back to command mode after every read-only action; doing so makes the next
number look like an unsupported command and turns normal human input into a mode
error.

This module is a presentation/composition guard only.  It does not cache Task/Event
truth, does not change Core actions, and does not change CalDAV ownership.  During one
home-menu visit it reuses the same presentation snapshot already owned by the
latency guard.  A successful explicit refresh replaces that snapshot for the rest of
the visit.  The user leaves menu mode only by choosing the explicit console item,
back/cancel, or an action that genuinely changes interaction mode.
"""
from __future__ import annotations

from typing import Any


_HOME_TITLE = "What do you want to do?"
_LEAVE_HOME = "Stay in console"
# These actions may change Task/Event/configuration state through nested shells.  The
# current snapshot must not be silently reused afterwards.  Until the home menu owns
# an explicit invalidation/refresh brick, return to the visibly labelled command
# console instead of showing stale live state.
_INVALIDATES_HOME_SNAPSHOT = frozenset(
    {
        "Task / Event management",
        "Upcoming settings",
        "Settings and setup",
    }
)


def _replace_instance_attribute(obj: Any, name: str, value: Any):
    """Temporarily replace a normal instance attribute without leaving a shadow."""
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
    """Make one guided-home visit persistent without changing command semantics."""
    if bool(getattr(module, "_smooth_home_installed", False)):
        return

    conversation = module.conversation
    original_home_menu = conversation._home_menu
    original_visible_call = conversation._visible_call

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
                value = bound_choose(title, items, **kwargs)
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

            # If the home prompt was never reached, preserve the original behavior.
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

            # Read-only screens, documentation, and cancelled/blocked guided-start
            # attempts stay in the same numbered-menu mode.  If an explicit Upcoming
            # refresh succeeded, tracking_visible_call already replaced the degraded
            # snapshot with that fresh result.

    conversation._home_menu = persistent_home_menu
    module._smooth_home_installed = True


__all__ = ["install"]
