from datetime import date

import pytest

from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.temporal.parser import TemporalParser


def test_august5_no_space_and_date_only():
    parser = TemporalParser(today_provider=lambda: date(2026, 1, 1))
    value = parser.parse_date("August5", bias="future")
    assert value == date(2026, 8, 5)
    assert type(value) is date


def test_aug5_no_space():
    parser = TemporalParser(today_provider=lambda: date(2026, 9, 1))
    assert parser.parse_date("Aug5", bias="future") == date(2027, 8, 5)


def test_yearless_leap_day_future_and_past_find_real_calendar_dates():
    parser = TemporalParser(today_provider=lambda: date(2026, 9, 6))

    assert parser.parse_date("Feb29", bias="future") == date(2028, 2, 29)
    assert parser.parse_date("2/29", bias="past") == date(2024, 2, 29)


def test_leap_day_future_after_same_year_occurrence_skips_to_next_leap_year():
    parser = TemporalParser(today_provider=lambda: date(2024, 3, 1))
    assert parser.parse_date("Feb29", bias="future") == date(2028, 2, 29)


def test_invalid_explicit_calendar_date_uses_public_validation_error():
    parser = TemporalParser(today_provider=lambda: date(2026, 1, 1))

    with pytest.raises(ValidationError, match="Invalid date"):
        parser.parse_date("Feb29 2025", bias="future")


def test_datetime_validates_bias_even_for_iso_input():
    parser = TemporalParser(today_provider=lambda: date(2026, 1, 1))

    with pytest.raises(ValidationError, match="bias must be one of"):
        parser.parse_datetime("2026-08-05T10:30", bias="sideways")


def test_time_rejects_non_text_with_validation_error():
    parser = TemporalParser(today_provider=lambda: date(2026, 1, 1))

    with pytest.raises(ValidationError, match="time text must be non-empty"):
        parser.parse_time(None)  # type: ignore[arg-type]
