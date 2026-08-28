from __future__ import annotations

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


def test_create_post_calls_wp_cli_and_returns_id():
    runner = Runner([SimpleNamespace(returncode=0, stdout="42\n", stderr="")])
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


def test_create_log_is_real_post_creation_not_in_memory_stub():
    runner = Runner([SimpleNamespace(returncode=0, stdout="101\n", stderr="")])
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    result = adapter.create_log("Finished report", title="Daily Log", status="publish")

    assert result == {"id": 101}
    command = runner.calls[0][0]
    assert command[:3] == ["wp", "post", "create"]
    assert "--post_title=Daily Log" in command
    assert "--post_content=Finished report" in command
    assert "--post_status=publish" in command
    assert "--post_type=post" in command


def test_update_post_calls_wp_cli():
    runner = Runner([SimpleNamespace(returncode=0, stdout="Success", stderr="")])
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
    runner = Runner([SimpleNamespace(returncode=1, stdout="", stderr="not installed")])
    adapter = WPCLIAdapter(executable="wp", runner=runner)

    assert adapter.test_connection() is False
    assert runner.calls[0][0] == ["wp", "core", "is-installed"]
