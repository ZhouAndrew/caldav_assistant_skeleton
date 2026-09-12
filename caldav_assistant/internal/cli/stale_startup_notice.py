"""Make cached startup state unmistakable in the zero-learning home screen."""
from __future__ import annotations

from typing import Any


_NOTICE = (
    "Warning: Cached Task/Event data — the live read missed the interactive "
    "deadline; this may be out of date."
)


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
    return any(
        bool(getattr(value, "stale", False))
        for value in values
        if value is not None
    )


def install(module: Any) -> None:
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
    module._stale_startup_notice_installed = True


__all__ = ["install"]
