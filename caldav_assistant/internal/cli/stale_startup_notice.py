"""Make background startup snapshots explicit without adding foreground network I/O."""
from __future__ import annotations

from typing import Any


_NOTICE = (
    "Warning: Cached Task/Event data from the background snapshot — this is the last "
    "locally verified state; background sync refreshes CalDAV independently."
)
_BACKGROUND_NO_CURRENT = (
    "  Background snapshot has no current Task. Start still verifies live CalDAV "
    "before any write."
)
_BACKGROUND_UNVERIFIED_CURRENT = (
    "  Current Task is not yet verified by this background Assistant generation. "
    "No Task will be started until verification succeeds."
)


def _value_is_stale(value: Any) -> bool:
    return value is not None and bool(getattr(value, "stale", False))


def _snapshot_is_stale(snapshot: Any) -> bool:
    if bool(getattr(snapshot, "stale", False)):
        return True
    values = [
        getattr(snapshot, "current_task", None),
        getattr(snapshot, "recommended", None),
        *(getattr(snapshot, "tasks", ()) or ()),
    ]
    values.extend(
        getattr(item, "value", None)
        for item in (getattr(snapshot, "upcoming", ()) or ())
    )
    return any(_value_is_stale(value) for value in values)


def _wrap_show_welcome(conversation: Any, original_show_welcome: Any):
    def show_welcome(app: Any):
        original_show = conversation._show
        buffered: list[Any] = []
        buffering = False

        def capture(current_app: Any, value: Any = "") -> None:
            nonlocal buffering
            if str(value) == "Now":
                buffering = True
            if buffering:
                buffered.append(value)
            else:
                original_show(current_app, value)

        conversation._show = capture
        try:
            snapshot = original_show_welcome(app)
        finally:
            conversation._show = original_show

        stale = _snapshot_is_stale(snapshot)
        verified = bool(getattr(snapshot, "current_work_verified", True))
        for value in buffered:
            text = str(value)
            if not verified and (
                text == "  No Task is currently being worked on."
                or text.startswith("  Current Task is still being verified")
            ):
                value = _BACKGROUND_UNVERIFIED_CURRENT
            elif stale and text == "  No Task is currently being worked on.":
                value = _BACKGROUND_NO_CURRENT
            elif stale and text.startswith("  ▶ "):
                value = f"{text}  [background snapshot]"
            original_show(app, value)
        return snapshot

    return show_welcome


def install(module: Any) -> None:
    """Label startup cache state; never add a duplicate live Start preflight."""
    if bool(getattr(module, "_stale_startup_notice_installed", False)):
        return

    conversation = module.conversation
    original_snapshot_text = conversation._snapshot_text

    def snapshot_text(snapshot: Any) -> str:
        body = original_snapshot_text(snapshot)
        if not _snapshot_is_stale(snapshot):
            return body
        return f"{_NOTICE}\n{body}"

    conversation._snapshot_text = snapshot_text

    # versioned_entrypoint installs this before conversation_live.run_cli() copies
    # live bricks into conversation_app, so guard both owners.  Crucially there is no
    # guided-Start wrapper here: Core TaskService already performs the authoritative
    # live Task + open-Work preflight immediately before mutation.  A second UI-level
    # network check only adds latency and cannot strengthen that authorization.
    module_show_welcome = getattr(module, "_show_welcome", None)
    if callable(module_show_welcome):
        module._show_welcome = _wrap_show_welcome(conversation, module_show_welcome)

    conversation_show_welcome = getattr(conversation, "_show_welcome", None)
    if callable(conversation_show_welcome):
        conversation._show_welcome = _wrap_show_welcome(
            conversation,
            conversation_show_welcome,
        )

    module._stale_startup_notice_installed = True


__all__ = ["install"]
