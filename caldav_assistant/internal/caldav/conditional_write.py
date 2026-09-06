"""Internal fast path for updating a just-read CalDAV object without re-reading it.

The public/frozen CalDAVAdapter contract intentionally remains unchanged.  Concrete
CalDAV adapter layers expose this only as an optional capability; Core services merely
probe that capability and remain independent of transport details.  A fast write is
used only when the object carries all transport facts produced by the concrete CalDAV
mapper: raw iCalendar data, resource URL, collection URL and ETag.  The reconstructed
python-caldav resource therefore sends the same ``If-Match`` PUT that a freshly
re-read resource would send.

If any prerequisite is absent (notably objects restored from the experimental SQLite
snapshot, which deliberately does not persist ``raw``), the helper returns ``None``
and the caller uses the ordinary adapter update path.  CalDAV remains authoritative.

A stale snapshot is also compatibility-safe: when the fast If-Match PUT gets a 412,
we immediately fall back to the pre-existing authoritative update path.  That path
re-reads the current server object and applies only the requested field changes, which
preserves the service's historical merge semantics while keeping the normal case to a
single read followed by a single conditional write.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...api import Event, Task
from ...api.v1.errors import ConflictError
from .library_adapter import _app_error
from .routing import CollectionRoutingCalDAVAdapter


_ETAG = "{DAV:}getetag"


def _url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


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


def _resource_from_snapshot(
    adapter: Any,
    obj: Task | Event,
) -> tuple[Any, Any, Any] | None:
    routed = _routing_adapter(adapter)
    if routed is None:
        return None

    raw = getattr(obj, "raw", None)
    resource_url = str(getattr(obj, "_caldav_url", "") or "").strip()
    collection_url = str(getattr(obj, "_caldav_collection_url", "") or "").strip()
    etag = getattr(obj, "_caldav_etag", None)
    if raw in (None, "", b"") or not resource_url or not collection_url or not etag:
        return None

    collection_key = _url(collection_url)
    resource_key = _url(resource_url)
    if not resource_key.startswith(collection_key + "/"):
        return None

    calendar = routed._selected_calendar(collection_url)
    inner = routed.adapter
    mapper_name = "_to_task" if isinstance(obj, Task) else "_to_event"
    editor_name = "_edit_task" if isinstance(obj, Task) else "_edit_event"
    mapper = getattr(inner, mapper_name, None)
    editor = getattr(inner, editor_name, None)
    class_for_data = getattr(calendar, "_calendar_comp_class_by_data", None)
    client = getattr(calendar, "client", None)
    if (
        calendar is None
        or not callable(mapper)
        or not callable(editor)
        or not callable(class_for_data)
        or client is None
    ):
        return None

    try:
        resource_class = class_for_data(raw)
        resource = resource_class(
            client,
            url=resource_url,
            data=raw,
            parent=calendar,
            props={_ETAG: str(etag)},
        )
    except Exception:
        return None

    return resource, editor, mapper


def _patch_experimental_snapshot(adapter: Any, kind: str, obj: Task | Event) -> None:
    patch = getattr(adapter, "_patch_snapshot", None)
    if not callable(patch):
        return
    try:
        patch(kind, obj=obj)
    except Exception:
        pass


def _ordinary_update(
    adapter: Any,
    obj: Task | Event,
    changes: Mapping[str, Any],
) -> Task | Event:
    if isinstance(obj, Task):
        return adapter.update_task(str(obj.id), dict(changes))
    return adapter.update_event(str(obj.id), dict(changes))


def _update_from_snapshot(
    adapter: Any,
    obj: Task | Event,
    changes: Mapping[str, Any],
) -> Task | Event | None:
    prepared = _resource_from_snapshot(adapter, obj)
    if prepared is None:
        return None
    resource, editor, mapper = prepared
    try:
        if changes:
            editor(resource, dict(changes))
            resource.save()
        result = mapper(resource, resource.parent)
    except Exception as exc:
        mapped = _app_error(exc)
        if isinstance(mapped, ConflictError):
            # Preserve the old update semantics.  A stale live object used to be
            # refreshed by the ordinary adapter immediately before editing.
            return _ordinary_update(adapter, obj, changes)
        raise mapped from exc

    kind = "task" if isinstance(result, Task) else "event"
    _patch_experimental_snapshot(adapter, kind, result)
    return result


def update_task_from_snapshot(
    adapter: Any,
    task: Task,
    changes: Mapping[str, Any],
) -> Task | None:
    result = _update_from_snapshot(adapter, task, changes)
    return result if isinstance(result, Task) else None


def update_event_from_snapshot(
    adapter: Any,
    event: Event,
    changes: Mapping[str, Any],
) -> Event | None:
    result = _update_from_snapshot(adapter, event, changes)
    return result if isinstance(result, Event) else None


__all__ = ["update_task_from_snapshot", "update_event_from_snapshot"]
