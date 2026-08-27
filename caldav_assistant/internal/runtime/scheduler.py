"""Low-resource wake scheduling primitives for the background service."""
from __future__ import annotations
from datetime import date, datetime, timezone
from time import monotonic
from typing import Any

class PlatformWakeScheduler:
    def monotonic(self) -> float: return monotonic()
    def wait(self, seconds: float, stop_event: Any) -> bool: return bool(stop_event.wait(max(0.0, float(seconds))))
    @staticmethod
    def _when(value: Any) -> datetime | None:
        if value is None: return None
        if isinstance(value, datetime): return value
        if isinstance(value, date): return None
        when = getattr(value, "when", None)
        return when if isinstance(when, datetime) else None
    def reminder_delay(self, reminders: Any, *, max_delay: float) -> float:
        next_due = getattr(reminders, "next_due", None)
        if not callable(next_due): return float(max_delay)
        when = self._when(next_due())
        if when is None or when.tzinfo is None: return float(max_delay)
        delay = (when.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(float(max_delay), delay))

__all__=["PlatformWakeScheduler"]
