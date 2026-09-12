"""Surface offline-cache state in the installed zero-learning home screen.

The stable CalDAV reliability layer marks cached Task/Event objects with ``stale``.
This presentation-only installer makes that state visible in the startup snapshot
without changing Task/Event data, Agenda ranking, or the public API.
"""
from __future__ import annotations

from typing import Any


_NOTICE = "Warning: Cached Task/Event data — CalDAV is unavailable; this may be out of date."


def _snapshot_has_stale_data(snapshot: Any) -> bool:
    if bool(getattr(snapshot, "stale", False)):
        return True
    values = [
        getattr(snapshot, "current_task", None),
        getattr(snapshot, "recommended", None),
    ]
    values.extend(
        getattr(item, "value", None)
        for item in (getattr(snapshot, "upcoming", ()) or ())
    )
    return any(bool(getattr(value, "stale", False)) for value in values if value is not None)


def install(module: Any) -> None:
    """Prepend one explicit warning when startup is rendered from stale facts."""
    if bool(getattr(module, "_stale_startup_notice_installed", False)):
        return

    conversation = module.conversation
    original_snapshot_text = conversation._snapshot_text

    def snapshot_text(snapshot: Any) -> str:
        body = original_snapshot_text(snapshot)
        if not _snapshot_has_stale_data(snapshot):
            return body
        return f"{_NOTICE}\n{body}"

    conversation._snapshot_text = snapshot_text
    module._stale_startup_notice_installed = True


__all__ = ["install"]
