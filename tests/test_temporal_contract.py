from datetime import date
from caldav_assistant.internal.temporal.parser import TemporalParser

def test_august5_no_space_and_date_only():
    parser = TemporalParser(today_provider=lambda: date(2026, 1, 1))
    value = parser.parse_date('August5', bias='future')
    assert value == date(2026, 8, 5)
    assert type(value) is date

def test_aug5_no_space():
    parser = TemporalParser(today_provider=lambda: date(2026, 9, 1))
    assert parser.parse_date('Aug5', bias='future') == date(2027, 8, 5)
