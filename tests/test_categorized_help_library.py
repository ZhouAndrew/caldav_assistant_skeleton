from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import NotFoundError
from caldav_assistant.internal.cli.actions import register_cli_builtin_commands
from caldav_assistant.internal.commands import CommandRegistry, CommandService


def _commands() -> CommandService:
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(commands=commands)
    register_cli_builtin_commands(commands, ctx)
    return commands


def test_bare_help_is_a_compact_action_library_not_a_registry_dump():
    commands = _commands()

    text = commands.run("help")

    assert text.startswith("Help · Action Library")
    assert "What do you want to do?" in text
    assert "agenda" in text
    assert "work" in text
    assert "manage" in text
    assert "records" in text
    assert "learn" in text
    assert "Open a category:  help work" in text
    assert "Show all actions:  help all" in text
    assert "  today —" not in text
    assert "  start —" not in text
    assert "edit-due" not in text


def test_help_category_expands_only_the_requested_family():
    commands = _commands()

    text = commands.run("help", "work")

    assert text.startswith("Help · Work")
    assert "  start —" in text
    assert "  pause —" in text
    assert "  resume —" in text
    assert "  done —" in text
    assert "  today —" not in text
    assert "  edit —" not in text
    assert "Back to categories: help" in text


def test_help_all_is_explicit_and_grouped():
    commands = _commands()

    text = commands.run("help", "all")

    assert text.startswith("Help · All Actions (grouped)")
    assert "Agenda [agenda]" in text
    assert "Work [work]" in text
    assert "Tasks & Events [manage]" in text
    assert "Logs & History [records]" in text
    assert "Learn & Navigate [learn]" in text
    assert "  today —" in text
    assert "  start —" in text
    assert "edit-due" not in text


def test_extension_and_user_actions_are_discoverable_without_flooding_root():
    commands = _commands()
    commands.register_extension(
        "school",
        lambda: None,
        extension="school_tools",
        description="School automation.",
    )
    commands.register_user(
        "morning",
        lambda: None,
        description="Personal morning flow.",
    )

    root = commands.run("help")
    added = commands.run("help", "added")

    assert "Added Actions" in root
    assert "  school —" not in root
    assert "  morning —" not in root
    assert "  school — School automation." in added
    assert "  morning — Personal morning flow." in added


def test_help_metadata_can_place_or_hide_future_actions():
    commands = _commands()
    commands.register_extension(
        "focus",
        lambda: None,
        extension="focus_tools",
        description="Focus workflow.",
        metadata={"help_category": "work"},
    )
    commands.register_extension(
        "internal-probe",
        lambda: None,
        extension="focus_tools",
        description="Internal support action.",
        metadata={"help_hidden": True},
    )

    work = commands.run("help", "work")
    all_actions = commands.run("help", "all")

    assert "  focus — Focus workflow." in work
    assert "internal-probe" not in all_actions


def test_detailed_command_help_and_unknown_command_behavior_are_preserved():
    commands = _commands()

    pause = commands.run("help", "pause")
    assert pause.startswith("pause\n")
    assert "Usage: pause" in pause
    assert "Writes / changes:" in pause
    assert "Activity Journal" in pause

    with pytest.raises(NotFoundError):
        commands.run("help", "definitely-not-a-command")
