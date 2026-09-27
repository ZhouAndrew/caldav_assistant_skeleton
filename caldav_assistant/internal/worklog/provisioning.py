"""Provision the dedicated CalDAV Assistant work-history calendar."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...api.v1.errors import NotFoundError, ValidationError
from ..settings.keys import CALDAV_WORKLOG_COLLECTION_URL


class WorkLogProvisioner:
    DEFAULT_NAME = "CalDAV Assistant History"
    DEFAULT_ID = "caldav-assistant-history"

    def __init__(self, settings: Any, adapter: Any) -> None:
        self.settings = settings
        self.adapter = adapter

    @staticmethod
    def _url(item: Any) -> str:
        if not isinstance(item, Mapping):
            return ""
        return str(item.get("url") or item.get("href") or item.get("id") or "").strip()

    @staticmethod
    def _name(item: Any) -> str:
        if not isinstance(item, Mapping):
            return ""
        return str(item.get("name") or item.get("display_name") or "").strip()

    @staticmethod
    def _components(item: Any) -> tuple[str, ...]:
        if not isinstance(item, Mapping):
            return ()
        raw = item.get("components") or item.get("supported_components") or ()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            return ()
        return tuple(str(value).upper() for value in raw)

    def ensure(self) -> dict[str, Any]:
        """Reuse the configured/dedicated calendar or create it once.

        No unrelated VEVENT calendar is guessed.  The dedicated display name is
        stable so Thunderbird and other CalDAV clients expose the same history.
        """
        existing = list(self.adapter.collections() or ())
        current = str(
            self.settings.get(CALDAV_WORKLOG_COLLECTION_URL, None) or ""
        ).strip()
        if current:
            match = next((item for item in existing if self._url(item) == current), None)
            if match is not None:
                return {
                    "created": False,
                    "configured": True,
                    "collection": dict(match),
                }
            # A stale URL must not silently remain authoritative.
            raise NotFoundError(f"Configured work history calendar not found: {current}")

        named = [
            item
            for item in existing
            if self._name(item).casefold() == self.DEFAULT_NAME.casefold()
            and (not self._components(item) or "VEVENT" in self._components(item))
        ]
        if len(named) > 1:
            raise ValidationError(
                "More than one CalDAV Assistant History calendar exists; "
                "refusing to choose silently"
            )
        if named:
            item = dict(named[0])
            url = self._url(item)
            if not url:
                raise ValidationError("Dedicated work history calendar has no URL")
            self.settings.set(CALDAV_WORKLOG_COLLECTION_URL, url)
            return {
                "created": False,
                "configured": True,
                "collection": item,
            }

        creator = getattr(self.adapter, "create_collection", None)
        if not callable(creator):
            raise ValidationError(
                "This CalDAV adapter cannot create the dedicated work history calendar"
            )
        item = creator(
            self.DEFAULT_NAME,
            components=["VEVENT"],
            collection_id=self.DEFAULT_ID,
        )
        url = self._url(item)
        if not url:
            raise ValidationError("Created work history calendar has no URL")
        self.settings.set(CALDAV_WORKLOG_COLLECTION_URL, url)
        return {
            "created": True,
            "configured": True,
            "collection": dict(item),
        }


__all__ = ["WorkLogProvisioner"]
