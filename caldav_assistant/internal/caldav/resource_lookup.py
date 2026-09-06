"""Concrete python-caldav UID lookup that returns body + ETag in one REPORT.

``Calendar.get_*_by_uid`` is a good general API, but the Assistant also needs the
resource ETag immediately after a read so a following mutation can use If-Match
without re-reading the same object.  This internal helper asks the existing
``Calendar.search`` implementation for both CalendarData and DAV:getetag in the same
calendar-query REPORT, then applies an exact UID check locally.

The helper is intentionally private to the concrete collection-routing path; the
frozen CalDAVAdapter contract and replacement adapters are unchanged.
"""
from __future__ import annotations

from typing import Any, Literal

from ...api.v1.errors import AmbiguousError, NotFoundError


def resource_by_uid_with_etag(
    calendar: Any,
    uid: str,
    *,
    component: Literal["task", "event"],
) -> Any:
    try:
        from caldav.elements import dav
    except ImportError:
        # The concrete LibraryCalDAVAdapter already maps a missing caldav package;
        # this path only runs when that adapter is active.
        raise

    search_args: dict[str, Any] = {
        "uid": uid,
        "include_completed": True,
        "post_filter": True,
        "_hacks": "insist",
        "props": [dav.GetEtag()],
    }
    if component == "task":
        search_args["todo"] = True
    elif component == "event":
        search_args["event"] = True
    else:  # pragma: no cover - Literal + internal callers make this defensive only.
        raise ValueError(f"unsupported calendar component: {component}")

    values = list(calendar.search(**search_args))
    exact = [
        resource
        for resource in values
        if str(getattr(resource, "id", "") or "") == uid
    ]
    if not exact:
        raise NotFoundError(uid)
    if len(exact) > 1:
        raise AmbiguousError(f"UID {uid!r} appears more than once in one CalDAV collection")
    return exact[0]


__all__ = ["resource_by_uid_with_etag"]
