"""Authoritative provider of the CalDAV ``base_url``."""
from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

from ...api.v1.errors import AmbiguousError, UnavailableError, ValidationError
from ..settings.keys import CALDAV_BASE_URL
from ..settings.service import SettingsService
from .contracts import BaseURLDiscoveryAdapter
from .models import BaseURLSource, ResolvedBaseURL


def normalize_base_url(value: str) -> str:
    """Validate and canonicalize a user/discovery supplied base URL."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("CalDAV base URL must be a non-empty string")

    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValidationError("CalDAV base URL must start with http:// or https://")
    if not parts.hostname:
        raise ValidationError("CalDAV base URL must include a hostname")
    if parts.username is not None or parts.password is not None:
        raise ValidationError("Credentials must not be embedded in the CalDAV base URL")
    if parts.query or parts.fragment:
        raise ValidationError("CalDAV base URL must not contain a query or fragment")

    # Accessing .port is deliberate: urllib raises ValueError for malformed or
    # out-of-range ports such as :99999. Translate that into our stable API error.
    try:
        port = parts.port
    except ValueError as exc:
        raise ValidationError("CalDAV base URL contains an invalid port") from exc
    if port is not None and not (1 <= port <= 65535):
        raise ValidationError("CalDAV base URL port must be between 1 and 65535")

    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


class ServerDiscovery:
    def __init__(
        self,
        settings: SettingsService,
        adapters: Sequence[BaseURLDiscoveryAdapter] | None = None,
    ) -> None:
        self._settings = settings
        self._adapters = tuple(adapters or ())

    @property
    def adapters(self):
        return self._adapters

    def get_base_url(self) -> str:
        return self.resolve().base_url

    def resolve(self) -> ResolvedBaseURL:
        saved = self._settings.get(CALDAV_BASE_URL)
        if saved:
            return ResolvedBaseURL(normalize_base_url(saved), BaseURLSource.SAVED)

        candidates = self.discover_candidates()
        if not candidates:
            raise UnavailableError(
                "No CalDAV base URL is configured or discovered; setup is required"
            )
        if len(candidates) > 1:
            raise AmbiguousError(
                "Multiple CalDAV base URLs were discovered; user selection is required"
            )
        return ResolvedBaseURL(candidates[0], BaseURLSource.DISCOVERED)

    def set_base_url(self, value: str) -> ResolvedBaseURL:
        normalized = normalize_base_url(value)
        self._settings.set(CALDAV_BASE_URL, normalized)
        return ResolvedBaseURL(normalized, BaseURLSource.MANUAL)

    def clear_base_url(self) -> None:
        self._settings.delete(CALDAV_BASE_URL)

    def discover_candidates(self) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for adapter in self._adapters:
            for candidate in adapter.discover_base_urls():
                normalized = normalize_base_url(candidate)
                if normalized not in seen:
                    seen.add(normalized)
                    unique.append(normalized)
        return unique
