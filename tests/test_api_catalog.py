from __future__ import annotations

import caldav_assistant.api.v1 as v1
from caldav_assistant import easy
from caldav_assistant.api import api_catalog, api_describe, api_exists, api_find
from caldav_assistant.api.v1 import protocols
from caldav_assistant.internal.cli.api_help import APIHelpAction


def test_catalog_covers_every_easy_export_with_usage():
    entries = api_catalog("easy")
    by_path = {entry.path: entry for entry in entries}

    for name in easy.__all__:
        path = f"easy.{name}"
        assert path in by_path
        assert by_path[path].usage.strip()
        assert by_path[path].summary.strip()


def test_catalog_covers_every_object_protocol_member():
    entries = {entry.path for entry in api_catalog("object")}
    namespaces = {
        "ctx.tasks": protocols.TasksAPI,
        "ctx.events": protocols.EventsAPI,
        "ctx.agenda": protocols.AgendaAPI,
        "ctx.reminders": protocols.RemindersAPI,
        "ctx.notifications": protocols.NotificationsAPI,
        "ctx.wordpress": protocols.WordPressAPI,
        "ctx.ui": protocols.UIAPI,
        "ctx.time": protocols.TemporalAPI,
        "ctx.commands": protocols.CommandsAPI,
        "ctx.activity": protocols.ActivityAPI,
        "ctx.settings": protocols.SettingsAPI,
        "ctx.session": protocols.SessionAPI,
    }

    for prefix, protocol in namespaces.items():
        assert prefix in entries
        for name in getattr(protocol, "__annotations__", {}):
            if not name.startswith("_"):
                assert f"{prefix}.{name}" in entries
        for name, value in vars(protocol).items():
            if not name.startswith("_") and callable(value):
                assert f"{prefix}.{name}" in entries


def test_catalog_covers_every_versioned_public_export():
    entries = {entry.path for entry in api_catalog("full")}
    for name in v1.__all__:
        assert f"v1.{name}" in entries


def test_exists_describe_and_search_use_real_public_interfaces():
    assert api_exists("easy.complete") is True
    assert api_exists("ctx.tasks.complete") is True
    assert api_exists("Task.start_task") is True
    assert api_exists("ctx.events.complete") is False
    assert api_exists("caldav_assistant.internal.tasks.service.TaskService") is False

    entry = api_describe("easy.write_log")
    assert entry.layer == "easy"
    assert "write_log" in entry.usage

    matches = api_find("reminder")
    assert matches
    assert any("reminder" in entry.path.casefold() for entry in matches)


def test_cli_api_browser_answers_existence_and_usage_without_runtime_context():
    action = APIHelpAction()

    overview = action()
    assert "Public Python API browser" in overview
    assert "api exists" in overview

    assert action("exists", "ctx.tasks.complete") == "YES — ctx.tasks.complete"
    assert action("exists", "ctx.events.complete") == "NO — ctx.events.complete"

    details = action("easy.complete")
    assert "exists: yes" in details
    assert "Usage:" in details
    assert "from caldav_assistant.easy import complete" in details

    search = action("search", "wordpress")
    assert "Public API matches" in search
    assert "ctx.wordpress" in search
