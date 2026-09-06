from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

from ...api.v1.errors import ValidationError


_MONTHS = {
    name.lower(): index
    for index, names in enumerate(
        [
            (),
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ]
    )
    for name in names
}

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_VALID_BIASES = {"any", "future", "past"}


class TemporalParser:
    def __init__(
        self,
        now_provider: Any = None,
        today_provider: Any = None,
        now: date | datetime | None = None,
    ) -> None:
        if now is not None:
            self._now_provider = lambda: (
                now if isinstance(now, datetime) else datetime.combine(now, time())
            )
        elif now_provider is not None:
            self._now_provider = now_provider
        elif today_provider is not None:
            self._now_provider = lambda: datetime.combine(today_provider(), time())
        else:
            self._now_provider = datetime.now

    def _now(self) -> datetime:
        value = self._now_provider()
        return value if isinstance(value, datetime) else datetime.combine(value, time())

    @staticmethod
    def _validate_bias(bias: str) -> None:
        if bias not in _VALID_BIASES:
            raise ValidationError("bias must be one of: any, future, past")

    @staticmethod
    def _text(value: Any, *, kind: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{kind} text must be non-empty")
        return value.strip()

    @staticmethod
    def _date_or_validation(year: int, month: int, day: int, original: str) -> date:
        try:
            return date(year, month, day)
        except ValueError as exc:
            raise ValidationError(f"Invalid date: {original}") from exc

    @staticmethod
    def _seek_valid_year(
        *,
        start_year: int,
        month: int,
        day: int,
        direction: int,
    ) -> date:
        """Find the next/previous calendar year that can represent month/day.

        This matters for yearless leap-day input. ``Feb29`` with ``bias='future'``
        must mean the next real February 29 rather than leaking ``ValueError`` from
        ``date(...)`` or ``replace(year=...)``.
        """
        year = start_year
        # Gregorian leap-day cycles repeat within four years; eight is deliberately
        # generous and also keeps malformed future calendar logic bounded.
        for _ in range(8):
            try:
                return date(year, month, day)
            except ValueError:
                year += direction
        raise ValidationError("No valid calendar date found for the requested year bias")

    def _yearless_date(
        self,
        month: int,
        day: int,
        *,
        today: date,
        bias: str,
        original: str,
    ) -> date:
        if bias == "future":
            candidate = self._seek_valid_year(
                start_year=today.year,
                month=month,
                day=day,
                direction=1,
            )
            if candidate < today:
                candidate = self._seek_valid_year(
                    start_year=candidate.year + 1,
                    month=month,
                    day=day,
                    direction=1,
                )
            return candidate

        if bias == "past":
            candidate = self._seek_valid_year(
                start_year=today.year,
                month=month,
                day=day,
                direction=-1,
            )
            if candidate > today:
                candidate = self._seek_valid_year(
                    start_year=candidate.year - 1,
                    month=month,
                    day=day,
                    direction=-1,
                )
            return candidate

        return self._date_or_validation(today.year, month, day, original)

    def parse_date(
        self,
        text: str,
        *,
        bias: str = "any",
        reference: date | datetime | None = None,
    ) -> date:
        self._validate_bias(bias)
        original = self._text(text, kind="date")
        normalized = " ".join(original.split()).lower()
        ref = reference or self._now()
        today = ref.date() if isinstance(ref, datetime) else ref

        if normalized == "today":
            return today
        if normalized == "tomorrow":
            return today + timedelta(days=1)
        if normalized == "yesterday":
            return today - timedelta(days=1)

        try:
            return date.fromisoformat(normalized)
        except ValueError:
            pass

        numeric = re.fullmatch(
            r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?",
            normalized,
        )
        if numeric:
            month = int(numeric.group(1))
            day = int(numeric.group(2))
            year_text = numeric.group(3)
            if year_text:
                year = int(year_text)
                if year < 100:
                    year += 2000
                return self._date_or_validation(year, month, day, original)
            return self._yearless_date(
                month,
                day,
                today=today,
                bias=bias,
                original=original,
            )

        named = re.fullmatch(
            r"([a-z]+)\s*(\d{1,2})(?:\s*,?\s*(\d{4}))?",
            normalized,
        )
        if named and named.group(1) in _MONTHS:
            month = _MONTHS[named.group(1)]
            day = int(named.group(2))
            year_text = named.group(3)
            if year_text:
                return self._date_or_validation(
                    int(year_text), month, day, original
                )
            return self._yearless_date(
                month,
                day,
                today=today,
                bias=bias,
                original=original,
            )

        next_prefix = normalized.startswith("next ")
        weekday = normalized[5:] if next_prefix else normalized
        if weekday in _WEEKDAYS:
            delta = (_WEEKDAYS[weekday] - today.weekday()) % 7
            if next_prefix:
                delta = delta + 7 if delta else 7
            elif bias == "future" and delta == 0:
                delta = 7
            elif bias == "past":
                back = (today.weekday() - _WEEKDAYS[weekday]) % 7
                if back == 0:
                    back = 7
                return today - timedelta(days=back)
            return today + timedelta(days=delta)

        raise ValidationError(f"Unrecognized date: {text}")

    def parse_time(self, text: str) -> time:
        normalized = self._text(text, kind="time").lower()
        for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I %p"):
            try:
                return datetime.strptime(normalized, fmt).time()
            except ValueError:
                pass
        raise ValidationError(f"Unrecognized time: {text}")

    def parse_datetime(
        self,
        text: str,
        *,
        bias: str = "any",
        reference: date | datetime | None = None,
    ) -> datetime:
        self._validate_bias(bias)
        original = self._text(text, kind="datetime")
        normalized = " ".join(original.split())

        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass

        trailing_time = re.fullmatch(
            r"(.+?)\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?)",
            normalized,
            re.I,
        )
        if trailing_time:
            parsed_date = self.parse_date(
                trailing_time.group(1),
                bias=bias,
                reference=reference,
            )
            parsed_time = self.parse_time(trailing_time.group(2))
            return datetime.combine(parsed_date, parsed_time)

        parsed_date = self.parse_date(
            normalized,
            bias=bias,
            reference=reference,
        )
        # The caller explicitly requested a datetime. Date-only input therefore maps
        # to the conventional start of that date; parse_date itself always remains
        # date-only and never smuggles in a time component.
        return datetime.combine(parsed_date, time())
