"""Internal server-side query helpers for configured CalDAV collections.

These helpers are optional accelerators above CollectionRoutingCalDAVAdapter.  They
never replace local semantic validation: CalDAV text matching is substring-oriented
and server behavior varies, so returned Event objects are always checked again with
the Assistant's exact `_matches` rules.  Unsupported/rejected server queries return
``None`` and callers fall back to their stable adapter path.
"""
from __future__ import annotations

from typing import Any

from ...api import Event
from .library_adapter import _matches
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

    ``description_contains`` is an internal transport hint: it is sent as the
    server-side DESCRIPTION text-match, while an ordinary ``description`` filter (if
    present) remains the local exact semantic check.  This lets WorkLog narrow on the
    stable single-line ``Task-UID: ...`` marker without asking servers to text-match a
    multi-line DESCRIPTION value byte-for-byte.
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

    description_contains = filters.get("description_contains")
    description = filters.get("description")
    if isinstance(description_contains, str) and description_contains.strip():
        search_args["description"] = description_contains.strip()
        pushed = True
    elif isinstance(description, str) and description.strip():
        search_args["description"] = description.strip()
        pushed = True
    if not pushed:
        return None

    local_filters = {
        key: value
        for key, value in filters.items()
        if key != "description_contains"
    }
    try:
        result: list[Event] = []
        for resource in search(**search_args):
            event = mapper(resource, calendar)
            if _matches(event, local_filters):
                result.append(event)
        return result
    except Exception:
        # This optimization must never make a server less compatible. The stable
        # scoped/full read remains the caller's fallback.
        return None


__all__ = ["query_events_in_collection"]
