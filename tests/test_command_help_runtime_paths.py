from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.internal.cli.semantics import format_command_help


_USER_VISIBLE_COMMANDS = (
    "today",
    "next",
    "current",
    "edit",
    "done",
    "start",
    "pause",
    "resume",
    "log",
    "help",
    "exit",
    "add",
    "tasks",
    "events",
    "edit-event",
    "remove",
    "history",
    "menu",
    "api",
    "settings",
    "background",
    "undo",
    "extensions",
    "extension",
    "clear",
    "shell",
    "run",
)


@pytest.mark.parametrize("name", _USER_VISIBLE_COMMANDS)
def test_every_visible_command_help_explains_runtime_path_not_only_label(name):
    entry = SimpleNamespace(
        name=name,
        description=f"Description for {name}",
        aliases=(),
        source="builtin" if name not in {"clear", "shell", "run"} else "extension:developer_tools",
    )

    text = format_command_help(entry)

    assert "Usage:" in text
    assert "Meaning:" in text
    assert "Runtime path:" in text
    assert "aliases:" in text
    assert "source:" in text
    assert "CLI" in text


def test_unknown_extension_command_still_gets_a_real_boundary_explanation():
    entry = SimpleNamespace(
        name="my-command",
        description="User extension command",
        aliases=(),
        source="extension:my_extension",
    )

    text = format_command_help(entry)

    assert "Runtime path:" in text
    assert "CommandRegistry" in text
    assert "extension:my_extension handler" in text
    assert "services it explicitly calls" in text
