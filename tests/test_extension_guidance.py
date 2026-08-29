from pathlib import Path

import pytest

from caldav_assistant.api.v1.errors import ExtensionError
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.extensions.cli import register_extension_cli_commands


class FakeSettings:
    def __init__(self, **values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def make(tmp_path, **settings):
    commands = CommandService(CommandRegistry())
    manager = ExtensionManager(
        commands,
        HookRegistry(),
        FakeSettings(**settings),
        root=tmp_path / "extensions",
    )
    register_extension_cli_commands(commands, manager)
    return manager, commands


def test_extension_guide_teaches_easy_api_and_task_event_boundary(tmp_path):
    _, commands = make(tmp_path)

    guide = commands.run("extension", "guide")

    assert "Python Easy API" in guide
    assert "from caldav_assistant.easy import" in guide
    assert "Task" in guide
    assert "Event" in guide
    assert "complete(task)" in guide
    assert "Event is not completed" in guide
    assert "extension errors NAME" in guide


def test_extension_guide_is_available_in_simplified_chinese(tmp_path):
    _, commands = make(tmp_path, **{"ui.locale": "zh-CN"})

    guide = commands.run("extension", "guide")

    assert "扩展功能以 Python Easy API 为第一入口" in guide
    assert "Task（任务）" in guide
    assert "Event（事件）" in guide
    assert "Event 不存在“完成”生命周期" in guide


def test_extension_new_creates_disabled_detailed_runnable_easy_template(tmp_path):
    manager, commands = make(tmp_path)

    result = commands.run("extension", "new", "school")
    record = manager.get("school")

    assert record.enabled is False
    assert record.status == "disabled"
    assert record.path == manager.root / "school.py"
    source = record.path.read_text(encoding="utf-8")

    # The generated file is now a real working template rather than the old tiny demo.
    assert len(source.splitlines()) >= 100
    compile(source, str(record.path), "exec")
    assert "from caldav_assistant.easy import" in source
    assert "caldav_assistant.internal" not in source
    assert "@command(" in source
    assert "'school'" in source
    assert "Event = something scheduled to occur" in source
    assert "Events do NOT have a completion lifecycle" in source

    # It demonstrates the major Scratch-like bricks without bypassing Core services.
    for brick in (
        "choose_task",
        "ask_date",
        "today_tasks",
        "overdue_tasks",
        "today_events",
        "start",
        "complete",
        "set_due",
        "confirm",
        "write_log",
    ):
        assert brick in source
    assert "school log TEXT" in source
    assert "extension reload school" in source
    assert "extension errors school" in source
    assert "extension enable school" in result

    loaded = manager.enable("school")
    assert loaded.status == "loaded"
    assert "school" in commands.registry


def test_extension_new_clears_stale_enabled_state_from_old_deleted_code(tmp_path):
    manager, commands = make(
        tmp_path,
        **{"extensions.enabled": {"school": True}},
    )

    commands.run("extension", "new", "school")
    record = manager.get("school")

    assert record.enabled is False
    assert record.status == "disabled"
    assert manager.settings.get("extensions.enabled") == {"school": False}
    assert "school" not in commands.registry


def test_extension_new_does_not_silently_replace_an_existing_command(tmp_path):
    manager, commands = make(tmp_path)
    commands.register_builtin("school", lambda: "core")

    with pytest.raises(ExtensionError, match="already exists"):
        commands.run("extension", "new", "school")

    assert not (manager.root / "school.py").exists()
    assert commands.run("school") == "core"


def test_extension_path_exposes_the_managed_directory_without_requiring_platform_knowledge(tmp_path):
    manager, commands = make(tmp_path)

    text = commands.run("extension", "path")

    assert str(manager.root) in text
    assert Path(manager.root).name == "extensions"


def test_extension_errors_name_shows_path_error_and_traceback(tmp_path):
    manager, commands = make(tmp_path)
    manager.root.mkdir(parents=True, exist_ok=True)
    source = manager.root / "broken.py"
    source.write_text('raise RuntimeError("boom")\n', encoding="utf-8")
    manager.discover()

    record = manager.enable("broken")
    assert record.status == "error"

    summary = commands.run("extension", "errors")
    detail = commands.run("extension", "errors", "broken")

    assert "RuntimeError: boom" in summary
    assert str(source) in detail
    assert "RuntimeError: boom" in detail
    assert "Traceback:" in detail
