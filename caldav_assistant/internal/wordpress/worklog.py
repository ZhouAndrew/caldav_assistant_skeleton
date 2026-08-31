"""Human-facing WordPress work-log formatting.

The Activity Journal and CalDAV Work VEVENTs keep detailed machine history.  This
module controls only the small human diary line written to WordPress.  The default
is deliberately terse while validated Settings allow each installation/user to
choose a different presentation without changing Task business logic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..settings.keys import WORDPRESS_WORKLOG_STYLE, WORDPRESS_WORKLOG_TEMPLATE


DEFAULT_WORKLOG_TEMPLATE = "{start}-{end} {task}"
_WORKLOG_STYLES = frozenset({"off", "compact", "detailed", "custom"})


class WorkLogFormatter:
    """Render one closed work interval for a human daily log."""

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings

    def _setting(self, key: str, default: Any) -> Any:
        getter = getattr(self.settings, "get", None)
        if not callable(getter):
            return default
        try:
            value = getter(key, default)
        except Exception:
            return default
        return default if value is None else value

    def style(self) -> str:
        value = str(self._setting(WORDPRESS_WORKLOG_STYLE, "compact") or "compact")
        value = value.strip().casefold()
        return value if value in _WORKLOG_STYLES else "compact"

    @staticmethod
    def _local(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.astimezone()
        return value.astimezone()

    @classmethod
    def _clock(cls, value: datetime) -> str:
        local = cls._local(value)
        return f"{local.hour}:{local.minute:02d}"

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m" if minutes else f"{hours}h"
        if minutes:
            return f"{minutes}m"
        return f"{secs}s"

    @staticmethod
    def _summary(task: Any) -> str:
        value = str(getattr(task, "summary", "") or "").strip()
        if value:
            return value
        uid = str(getattr(task, "id", "") or "").strip()
        return uid or "Task"

    def render_segment(
        self,
        task: Any,
        start: datetime,
        end: datetime,
        *,
        status: str = "worked",
    ) -> str | None:
        """Return one human entry or ``None`` when WordPress work logging is off."""
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            return None
        if end < start:
            return None

        style = self.style()
        if style == "off":
            return None

        summary = self._summary(task)
        uid = str(getattr(task, "id", "") or "").strip()
        seconds = (end - start).total_seconds()
        fields = {
            "start": self._clock(start),
            "end": self._clock(end),
            "task": summary,
            "uid": uid,
            "duration": self._duration(seconds),
            "duration_minutes": max(0, int(seconds // 60)),
            "status": str(status or "worked"),
            "start_iso": self._local(start).isoformat(timespec="seconds"),
            "end_iso": self._local(end).isoformat(timespec="seconds"),
        }
        compact = DEFAULT_WORKLOG_TEMPLATE.format_map(fields)

        if style == "compact":
            return compact
        if style == "custom":
            template = str(
                self._setting(WORDPRESS_WORKLOG_TEMPLATE, DEFAULT_WORKLOG_TEMPLATE)
                or DEFAULT_WORKLOG_TEMPLATE
            )
            try:
                rendered = template.format_map(fields).strip()
            except (KeyError, ValueError):
                return compact
            return rendered or compact

        return "\n".join(
            [
                compact,
                f"Duration: {fields['duration']}",
                f"Task UID: {uid or '—'}",
                f"Start: {fields['start_iso']}",
                f"End: {fields['end_iso']}",
                f"Status: {fields['status']}",
            ]
        )


__all__ = ["DEFAULT_WORKLOG_TEMPLATE", "WorkLogFormatter"]
