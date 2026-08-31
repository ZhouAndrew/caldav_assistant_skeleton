from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

from caldav_assistant.internal.wordpress.transports import WPCLIAdapter


class Runner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        return self.responses.pop(0)


def _response(stdout=""):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_read_daily_log_returns_exact_remote_title_not_a_normalized_reconstruction():
    actual_title = "Aug 30  Sunday  2026"
    actual_content = "<!-- wp:paragraph -->\n<p>08:40 Real WordPress content</p>\n<!-- /wp:paragraph -->"
    post_list = json.dumps([{"ID": 91, "post_title": actual_title}])
    runner = Runner(
        [
            _response(post_list),
            _response(actual_content),
        ]
    )
    adapter = WPCLIAdapter(
        executable="wp",
        runner=runner,
        clock=lambda: datetime(2026, 8, 30, 0, 40, tzinfo=timezone.utc),
    )

    result = adapter.read_daily_log()

    assert result == {
        "id": 91,
        "title": actual_title,
        "content": actual_content,
    }
    assert runner.calls[1][0] == ["wp", "post", "get", "91", "--field=post_content"]


def test_worklog_entry_can_render_exact_human_line_without_logged_at_clock():
    rendered = WPCLIAdapter._render_log_entry(
        "5:00-5:10 Anki",
        at=datetime(2026, 8, 31, 5, 10, tzinfo=timezone.utc),
        show_clock=False,
    )

    assert rendered == (
        "<!-- wp:paragraph -->\n"
        "<p>5:00-5:10 Anki</p>\n"
        "<!-- /wp:paragraph -->"
    )
    assert "05:10 5:00" not in rendered
