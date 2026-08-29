from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from caldav_assistant.internal.wordpress.transports import WPCLIAdapter


class Runner:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if self.responses:
            return self.responses.pop(0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def response(stdout="", *, returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_create_post_calls_wp_cli_and_returns_id():
    runner = Runner([response("42\n")])
    adapter = WPCLIAdapter(
        "/var/www/html/wordpress",
        executable="/usr/local/bin/wp",
        runner=runner,
    )

    result = adapter.create_post("Title", "Body", post_status="draft")

    assert result == {"id": 42}
    command = runner.calls[0][0]
    assert command[:4] == [
        "/usr/local/bin/wp",
        "--path=/var/www/html/wordpress",
        "post",
        "create",
    ]
    assert "--post_title=Title" in command
    assert "--post_content=Body" in command
    assert "--post_status=draft" in command
    assert command[-1] == "--porcelain"


def test_create_log_creates_one_daily_post_when_today_post_is_missing():
    runner = Runner([response("[]"), response("101\n")])
    adapter = WPCLIAdapter(
        executable="wp",
        runner=runner,
        clock=lambda: datetime(2026, 8, 29, 14, 5, tzinfo=timezone.utc),
    )

    result = adapter.create_log("Finished report", _request_id="req-1")

    assert result == {"id": 101}
    lookup = runner.calls[0][0]
    assert lookup[:3] == ["wp", "post", "list"]
    assert "--search=August 29 Saturday 2026" in lookup
    assert "--post_status=any" in lookup

    create = runner.calls[1][0]
    assert create[:3] == ["wp", "post", "create"]
    assert "--post_title=August 29 Saturday 2026" in create
    content_arg = next(item for item in create if item.startswith("--post_content="))
    assert "caldav-assistant-log:req-1" in content_arg
    assert "<p>14:05 Finished report</p>" in content_arg
    assert "--post_status=draft" in create
    assert "--post_type=post" in create


def test_create_log_appends_to_existing_daily_post_instead_of_creating_another():
    existing = "<!-- wp:paragraph -->\n<p>06:51 I woke up</p>\n<!-- /wp:paragraph -->"
    runner = Runner(
        [
            response('[{"ID":13554,"post_title":"August 29 Saturday 2026"}]'),
            response(existing),
            response("Success"),
        ]
    )
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    result = adapter.create_log(
        "break",
        _logged_at="2026-08-29T14:05:00+08:00",
        _request_id="req-break",
    )

    assert result == {"id": 13554}
    assert len(runner.calls) == 3
    assert runner.calls[1][0] == ["wp", "post", "get", "13554", "--field=post_content"]
    update = runner.calls[2][0]
    assert update[:4] == ["wp", "post", "update", "13554"]
    content_arg = next(item for item in update if item.startswith("--post_content="))
    assert "06:51 I woke up" in content_arg
    assert "caldav-assistant-log:req-break" in content_arg
    assert "<p>14:05 break</p>" in content_arg


def test_daily_log_retry_is_idempotent_when_hidden_request_marker_already_exists():
    existing = (
        "<!-- caldav-assistant-log:req-break -->\n"
        "<!-- wp:paragraph -->\n<p>14:05 break</p>\n<!-- /wp:paragraph -->"
    )
    runner = Runner(
        [
            response('[{"ID":13554,"post_title":"August 29 Saturday 2026"}]'),
            response(existing),
        ]
    )
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    result = adapter.create_log(
        "break",
        _logged_at="2026-08-29T14:05:00+08:00",
        _request_id="req-break",
    )

    assert result == {"id": 13554}
    assert len(runner.calls) == 2
    assert all(call[0][2:4] != ["post", "update"] for call in runner.calls)


def test_explicit_log_title_becomes_entry_heading_not_daily_post_title():
    runner = Runner([response("[]"), response("101\n")])
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    adapter.create_log(
        "Task: Anki",
        title="Started — Anki",
        _logged_at="2026-08-29T14:05:00+08:00",
        _request_id="req-start",
    )

    create = runner.calls[1][0]
    assert "--post_title=August 29 Saturday 2026" in create
    content_arg = next(item for item in create if item.startswith("--post_content="))
    assert "14:05 <strong>Started — Anki</strong>" in content_arg
    assert "Task: Anki" in content_arg


def test_update_post_calls_wp_cli():
    runner = Runner([response("Success")])
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    result = adapter.update_post(7, post_status="publish")

    assert result == {"id": 7}
    assert runner.calls[0][0] == [
        "wp",
        "post",
        "update",
        "7",
        "--post_status=publish",
    ]


def test_connection_returns_false_when_wp_cli_fails():
    runner = Runner([response(returncode=1, stderr="not installed")])
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    assert adapter.test_connection() is False
    assert runner.calls[0][0] == ["wp", "core", "is-installed"]
