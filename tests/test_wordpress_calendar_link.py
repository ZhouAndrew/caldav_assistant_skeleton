from __future__ import annotations

from caldav_assistant.internal.integrations import WordPressCalendarLinker


class WorkLog:
    def __init__(self):
        self.calls = []

    def link_wordpress(self, event_id, post_url, *, attachment_urls=None):
        self.calls.append((event_id, post_url, list(attachment_urls or ())))


def payload(**metadata):
    return {
        "operation": "create_log",
        "args": {
            "metadata": metadata,
        },
    }


def test_calendar_link_is_applied_when_work_log_requests_default_linking():
    worklog = WorkLog()
    linker = WordPressCalendarLinker(worklog)

    linker.after_delivery(
        "create_log",
        {"id": 42, "post_url": "https://example.test/log/42"},
        payload(_calendar_link=True, _work_event_id="work-1"),
    )

    assert worklog.calls == [
        ("work-1", "https://example.test/log/42", []),
    ]


def test_attachment_direct_link_is_separate_and_optional():
    worklog = WorkLog()
    linker = WordPressCalendarLinker(worklog)
    request = {
        "operation": "attach_file",
        "args": {
            "metadata": {
                "_calendar_link": True,
                "_calendar_attachment_link": True,
                "_work_event_id": "work-2",
            }
        },
    }

    linker.after_delivery(
        "attach_file",
        {
            "post_url": "https://example.test/log/42",
            "url": "https://example.test/uploads/photo.png",
        },
        request,
    )

    assert worklog.calls == [
        (
            "work-2",
            "https://example.test/log/42",
            ["https://example.test/uploads/photo.png"],
        )
    ]


def test_no_calendar_link_request_leaves_event_untouched():
    worklog = WorkLog()
    linker = WordPressCalendarLinker(worklog)

    linker.after_delivery(
        "create_log",
        {"post_url": "https://example.test/log/42"},
        payload(_calendar_link=False, _work_event_id="work-1"),
    )

    assert worklog.calls == []
