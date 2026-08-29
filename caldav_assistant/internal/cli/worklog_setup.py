"""First-run setup brick for optional CalDAV-backed work history.

This module is deliberately CLI composition only. It reads and writes settings
through the public settings namespace and asks the user through the public UI
namespace. It never talks to CalDAV XML/HTTP directly.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ...api.v1.errors import ValidationError
from ..settings.keys import CALDAV_WORKLOG_COLLECTION_URL


class WorkLogSetup:
    """Offer a VEVENT work-history collection without making it mandatory."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def _show(self, value: Any) -> None:
        show = getattr(self.ctx.ui, "show", None)
        if callable(show):
            show(value)

    @staticmethod
    def _collection_name(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        return str(
            item.get("name")
            or item.get("display_name")
            or item.get("url")
            or item.get("href")
            or item
        )

    @staticmethod
    def _collection_url(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        value = item.get("url") or item.get("href") or item.get("id")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _components(item: Any) -> tuple[str, ...]:
        if not isinstance(item, dict):
            return ()
        raw = item.get("components") or item.get("supported_components") or ()
        return tuple(str(value).upper() for value in raw)

    def ensure(self) -> bool:
        settings = getattr(self.ctx, "settings", None)
        if settings is None:
            return True

        getter = getattr(settings, "get", None)
        setter = getattr(settings, "set", None)
        collections = getattr(settings, "caldav_collections", None)
        choose = getattr(self.ctx.ui, "choose", None)

        # Small/unit contexts may intentionally omit production setup APIs.  The
        # Task service will use Activity Journal fallback when no Work VEVENT store
        # is configured.
        if not callable(getter) or not callable(collections):
            return True

        current = getter(CALDAV_WORKLOG_COLLECTION_URL, None)
        if isinstance(current, str) and current.strip():
            return True

        if not callable(setter) or not callable(choose):
            self._show(
                "Work history calendar is not configured. Continuing with the "
                "Activity Journal fallback."
            )
            return True

        items = list(collections() or ())
        compatible = [
            item
            for item in items
            if "VEVENT" in self._components(item) and self._collection_url(item)
        ]
        if not compatible:
            self._show(
                "No VEVENT calendar is available for detailed work intervals. "
                "Starting the Task anyway; lifecycle history will use the Activity Journal."
            )
            return True

        self._show(
            "Optional work history setup — choose a VEVENT calendar to store precise "
            "Start/Pause/Resume intervals. Cancel to continue with Activity Journal only."
        )

        names = [self._collection_name(item) for item in compatible]
        duplicates = Counter(names)
        labels: list[str] = []
        mapping: dict[str, tuple[str, str]] = {}
        for item, name in zip(compatible, names):
            url = str(self._collection_url(item))
            components = self._components(item)
            suffix = " [" + ", ".join(components) + "]" if components else ""
            label = f"{name}{suffix}"
            if duplicates[name] > 1:
                label += f" — {url}"
            labels.append(label)
            mapping[label] = (url, name)

        selected = choose("Work log collection", labels)
        if selected is None:
            self._show(
                "No work history calendar selected. Starting the Task with Activity Journal fallback."
            )
            return True

        chosen = mapping.get(str(selected))
        if chosen is None:
            raise ValidationError("Unknown work log collection selection")
        url, name = chosen
        setter(CALDAV_WORKLOG_COLLECTION_URL, url)
        self._show(f"✓ Work log collection: {name}")
        return True


__all__ = ["WorkLogSetup"]
