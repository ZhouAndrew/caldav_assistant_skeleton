"""Internal server-side query helpers for configured CalDAV collections.

These helpers are optional accelerators above CollectionRoutingCalDAVAdapter.  They
never replace local semantic validation: CalDAV servers commonly implement text
property filters as substring matches, so returned Event objects are always checked
again with the Assistant's exact `_matches` rules.  Unsupported/rejected server
queries return ``None`` and callers fall back to their stable adapter path.
"""
from __future__ import annotations

from typing import Any

from ...api import Event
from .library_adapter import _app_error, _matches
from .routing import CollectionRoutingCalDAVAdapter


def _routing_adapter(adapter: Any) -> CollectionRoutingCalDAVAdapter | None:
    current = adapter
    seen: set[int] = set()
    for _ in range(6):
        if isinstance(current, CollectionRoutingCalDAVAdapter):
            return current
        marker = id(current)
        if marker in seen:
            return None
        seen.add(marker)
        current = getattr(current, "adapter", None)
        if current is None:
            return None
    return None


def query_events_in_collection(
    adapter: Any,
    collection_url: str,
    **filters: Any,
) -> list[Event] | None:
    """Try one server-side VEVENT property-filter REPORT in a known collection.

    Currently only simple string ``category`` and ``description`` filters are pushed
    to python-caldav.  Any other filters remain local and exact.  ``None`` means the
    optimized brick is unavailable/rejected; an empty list is a successful query with
    no matching events.
    """
    routed = _routing_adapter(adapter)
    if routed is None:
        return None
    try:
        calendar = routed._selected_calendar(collection_url)
    except Exception:
        return None
    inner = routed.adapter
    mapper = getattr(inner, "_to_event", None)
    search = getattr(calendar, "search", None)
    if calendar is None or not callable(mapper) or not callable(search):
        return None

    search_args: dict[str, Any] = {"event": True, "expand": False}
    pushed = False
    category = filters.get("category")
    if isinstance(category, str) and category.strip():
        search_args["category"] = category.strip()
        pushed = True
    description = filters.get("description")
    if isinstance(description, str) and description.strip():
        search_args["description"] = description.strip()
        pushed = True
    if not pushed:
        return None

    try:
        result: list[Event] = []
        for resource in search(**search_args):
            event = mapper(resource, calendar)
            if _matches(event, filters):
                result.append(event)
        return result
    except Exception as exc:
        # Server-side property filters are an optional optimization. Protocol or
        # compatibility failures intentionally fall back instead of becoming user
        # visible. Application-level errors are likewise left to the stable path.
        try:
            _app_error(exc)
        except Exception:
            pass
        return None


__all__ = ["query_events_in_collection"]
