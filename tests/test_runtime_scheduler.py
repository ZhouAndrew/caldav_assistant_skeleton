from datetime import date
from threading import Event
from caldav_assistant.internal.runtime.scheduler import PlatformWakeScheduler

def test_date_only_is_not_coerced_to_midnight():
    class R:
        def next_due(self): return date(2026,8,30)
    assert PlatformWakeScheduler().reminder_delay(R(),max_delay=12)==12

def test_wait_is_interruptible():
    event=Event(); event.set(); assert PlatformWakeScheduler().wait(100,event) is True
