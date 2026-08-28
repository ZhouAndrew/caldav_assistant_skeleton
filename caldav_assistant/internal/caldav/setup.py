"""Internal production CalDAV setup orchestration.

Coordinates existing Settings, ServerDiscovery and CalDAVAdapter boundaries.
It owns no Task/Event business logic and does not expose stored credentials.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...api.v1.errors import AmbiguousError, UnavailableError, ValidationError
from ..settings.keys import CALDAV_CREDENTIALS


class CalDAVSetupService:
    def __init__(self, settings: Any, discovery: Any, adapter: Any) -> None:
        if settings is None or discovery is None or adapter is None:
            raise TypeError("settings, discovery and adapter are required")
        self.settings = settings
        self.discovery = discovery
        self.adapter = adapter

    @staticmethod
    def _text(value: Any, *, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{label} must be non-empty text")
        return value.strip()

    def _reconnect(self) -> None:
        close = getattr(self.adapter, "close", None)
        if callable(close):
            close()

    def _credentials_configured(self) -> bool:
        value = self.settings.get(CALDAV_CREDENTIALS, None)
        if value is None:
            return False
        if not isinstance(value, Mapping):
            raise ValidationError("Stored CalDAV credentials are invalid")
        return any(bool(item) for item in value.values())

    def status(self) -> dict[str, Any]:
        discovered_candidates: list[str] = []
        try:
            resolved = self.discovery.resolve()
            base_url = (
                getattr(resolved, "base_url", None)
                or getattr(resolved, "url", None)
                or str(resolved)
            )
            source_obj = getattr(resolved, "source", None)
            source = (
                getattr(source_obj, "value", None)
                or (str(source_obj) if source_obj is not None else None)
            )
        except UnavailableError:
            # First-run "not configured/discovered" is a normal setup state.
            base_url = None
            source = None
        except AmbiguousError:
            # Do not guess. Keep the setup UI reachable and surface the exact
            # discovery candidates so PromptKit/Menu can ask the user to choose.
            discover = getattr(self.discovery, "discover_candidates", None)
            discovered_candidates = (
                [str(item) for item in discover()]
                if callable(discover)
                else []
            )
            base_url = None
            source = "ambiguous"

        return {
            "base_url": base_url,
            "base_url_configured": bool(base_url),
            "base_url_source": source,
            "discovered_candidates": discovered_candidates,
            "credentials_configured": self._credentials_configured(),
        }

    def set_base_url(self, value: str) -> dict[str, Any]:
        resolved = self.discovery.set_base_url(
            self._text(value, label="CalDAV server")
        )
        normalized = (
            getattr(resolved, "base_url", None)
            or getattr(resolved, "url", None)
            or str(resolved)
        )
        self._reconnect()
        result = self.status()
        result["base_url"] = normalized
        result["base_url_configured"] = True
        return result

    def set_credentials(self, username: str, password: str) -> dict[str, Any]:
        credentials = {
            "username": self._text(username, label="CalDAV username"),
            "password": self._text(password, label="CalDAV password"),
        }
        previous = self.settings.get(CALDAV_CREDENTIALS, None)
        normalized = self.settings.set(CALDAV_CREDENTIALS, credentials)
        try:
            # Update the already-running transport instance, then drop its cached
            # client. After daemon restart bootstrap reads the persisted value.
            self.adapter.credentials = normalized
        except Exception as exc:
            if previous is None:
                self.settings.delete(CALDAV_CREDENTIALS)
            else:
                self.settings.set(CALDAV_CREDENTIALS, previous)
            raise ValidationError(
                "CalDAV adapter rejected configured credentials"
            ) from exc
        self._reconnect()
        return self.status()

    def clear_credentials(self) -> dict[str, Any]:
        previous = self.settings.get(CALDAV_CREDENTIALS, None)
        self.settings.delete(CALDAV_CREDENTIALS)
        try:
            self.adapter.credentials = None
        except Exception:
            if previous is not None:
                self.settings.set(CALDAV_CREDENTIALS, previous)
            raise
        self._reconnect()
        return self.status()

    @staticmethod
    def _collection_view(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            source = dict(value)
            result: dict[str, Any] = {}
            for key in (
                "id", "name", "display_name", "url", "href",
                "kind", "type", "supported_components", "components",
            ):
                if key not in source:
                    continue
                item = source[key]
                if isinstance(item, (str, int, float, bool, type(None))):
                    result[key] = item
                elif isinstance(item, Sequence) and not isinstance(
                    item, (str, bytes, bytearray)
                ):
                    result[key] = [str(part) for part in item]
                else:
                    result[key] = str(item)
            if result:
                return result

        name = (
            getattr(value, "name", None)
            or getattr(value, "display_name", None)
            or getattr(value, "url", None)
            or str(value)
        )
        result = {"name": str(name)}
        url = getattr(value, "url", None)
        if url is not None:
            result["url"] = str(url)
        return result

    def collections(self) -> list[dict[str, Any]]:
        return [
            self._collection_view(item)
            for item in (self.adapter.collections() or ())
        ]

    def test_connection(self) -> dict[str, Any]:
        # An authenticated collection operation is the connection test; merely
        # saving/normalizing a URL is not a successful connection.
        items = self.collections()
        status = self.status()
        return {
            "ok": True,
            "base_url": status.get("base_url"),
            "credentials_configured": status.get("credentials_configured", False),
            "collection_count": len(items),
            "collections": items,
        }


__all__ = ["CalDAVSetupService"]
