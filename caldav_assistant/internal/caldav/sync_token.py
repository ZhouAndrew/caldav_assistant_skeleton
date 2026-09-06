"""Optional RFC 6578 sync-token transport for production collection routing.

This module is deliberately internal.  The frozen CalDAVAdapter contract remains
unchanged; SyncEngine opportunistically uses this capability when the production
routing adapter exposes configured Task/Event collection URLs and python-caldav's
sync-token API.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...api import Event, Task
from ...api.v1.errors import UnavailableError
from .library_adapter import _app_error, _component


def _url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


class SyncTokenUnavailable(Exception):
    """The selected server/adapter cannot currently provide RFC 6578 deltas."""


class SyncTokenStale(Exception):
    """A previously stored token is no longer accepted by the server."""


class SyncTokenTransport:
    """Small optional bridge from CollectionRoutingCalDAVAdapter to RFC 6578."""

    def __init__(self, routed_adapter: Any) -> None:
        self.routed = routed_adapter

    def role_urls(self) -> dict[str, str]:
        task_provider = getattr(self.routed, "task_collection_url", None)
        event_provider = getattr(self.routed, "event_collection_url", None)
        if not callable(task_provider) or not callable(event_provider):
            return {}
        tasks = _url(task_provider())
        events = _url(event_provider())
        if not tasks or not events:
            return {}
        return {"tasks": tasks, "events": events}

    def available(self) -> bool:
        if not self.role_urls():
            return False
        selector = getattr(self.routed, "_selected_calendar", None)
        inner = getattr(self.routed, "adapter", None)
        return (
            callable(selector)
            and callable(getattr(inner, "_to_task", None))
            and callable(getattr(inner, "_to_event", None))
        )

    def _calendar(self, url: str) -> Any:
        selector = getattr(self.routed, "_selected_calendar", None)
        if not callable(selector):
            raise SyncTokenUnavailable("collection routing has no direct calendar selector")
        calendar = selector(url)
        if calendar is None:
            raise SyncTokenUnavailable("configured collection cannot be resolved")
        method = getattr(calendar, "get_objects_by_sync_token", None)
        if not callable(method):
            raise SyncTokenUnavailable("CalDAV library has no sync-token API")
        return calendar

    @staticmethod
    def _protocol_error(exc: Exception, *, has_old_token: bool) -> Exception:
        name = type(exc).__name__
        text = str(exc) or name
        if name == "ReportError":
            return SyncTokenStale(text) if has_old_token else SyncTokenUnavailable(text)
        # RFC 6578 uses a 403 valid-sync-token precondition for an expired/unknown
        # token.  python-caldav may surface that response as AuthorizationError.
        if has_old_token and name == "AuthorizationError":
            return SyncTokenStale(text)
        return _app_error(exc)

    def seed(self) -> dict[str, Any]:
        """Read one opaque token per unique configured collection, without data."""
        role_urls = self.role_urls()
        if not role_urls:
            raise SyncTokenUnavailable("Task/Event collection roles are not configured")

        tokens: dict[str, str] = {}
        for url in dict.fromkeys(role_urls.values()):
            calendar = self._calendar(url)
            try:
                result = calendar.get_objects_by_sync_token(
                    None,
                    load_objects=False,
                    disable_fallback=True,
                )
            except Exception as exc:
                mapped = self._protocol_error(exc, has_old_token=False)
                raise mapped from exc
            token = getattr(result, "sync_token", None)
            if token in (None, ""):
                raise SyncTokenUnavailable("server returned no sync-token")
            text = str(token)
            if text.startswith("fake-"):
                raise SyncTokenUnavailable("server returned an emulated sync-token")
            tokens[url] = text

        return {"role_urls": role_urls, "tokens": tokens}

    def changes(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Return only changed resources/deleted URLs since stored opaque tokens."""
        role_urls = self.role_urls()
        stored_urls = state.get("role_urls") if isinstance(state, Mapping) else None
        stored_tokens = state.get("tokens") if isinstance(state, Mapping) else None
        if not isinstance(stored_urls, Mapping) or dict(stored_urls) != role_urls:
            raise SyncTokenStale("configured collection roles changed")
        if not isinstance(stored_tokens, Mapping):
            raise SyncTokenStale("stored sync-token state is missing")

        inner = getattr(self.routed, "adapter", None)
        task_mapper = getattr(inner, "_to_task", None)
        event_mapper = getattr(inner, "_to_event", None)
        if not callable(task_mapper) or not callable(event_mapper):
            raise SyncTokenUnavailable("concrete CalDAV mappers are unavailable")

        tasks: list[Task] = []
        events: list[Event] = []
        deleted_urls: list[str] = []
        next_tokens: dict[str, str] = {}

        for url in dict.fromkeys(role_urls.values()):
            old_token = stored_tokens.get(url)
            if old_token in (None, ""):
                raise SyncTokenStale(f"stored sync-token missing for {url}")
            calendar = self._calendar(url)
            try:
                result = calendar.get_objects_by_sync_token(
                    str(old_token),
                    load_objects=True,
                    disable_fallback=True,
                )
            except Exception as exc:
                mapped = self._protocol_error(exc, has_old_token=True)
                raise mapped from exc

            token = getattr(result, "sync_token", None)
            if token in (None, ""):
                raise SyncTokenStale("server returned no replacement sync-token")
            text = str(token)
            if text.startswith("fake-"):
                raise SyncTokenUnavailable("server fell back to an emulated sync-token")
            next_tokens[url] = text

            for resource in list(result or ()):
                resource_url = _url(getattr(resource, "url", ""))
                # python-caldav leaves a deleted resource unloaded after its
                # load_objects=True NotFound handling.  Deletion classification is
                # by URL against the previous verified snapshot in SyncEngine.
                if getattr(resource, "_data", None) is None:
                    if resource_url:
                        deleted_urls.append(resource_url)
                    continue

                try:
                    component = _component(resource)
                    name = str(getattr(component, "name", "") or "").upper()
                    if name == "VTODO":
                        tasks.append(task_mapper(resource, calendar))
                    elif name == "VEVENT":
                        events.append(event_mapper(resource, calendar))
                    else:
                        # VJOURNAL/other objects may share a CalDAV collection but
                        # are outside this Assistant's Task/Event snapshot.
                        continue
                except Exception as exc:
                    raise _app_error(exc) from exc

        return {
            "role_urls": role_urls,
            "tokens": next_tokens,
            "tasks": tasks,
            "events": events,
            "deleted_urls": sorted(set(deleted_urls)),
        }


__all__ = [
    "SyncTokenTransport",
    "SyncTokenUnavailable",
    "SyncTokenStale",
]
