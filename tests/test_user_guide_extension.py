from pathlib import Path
from types import SimpleNamespace

from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.runtime.current_context import (
    bind_current_context,
    clear_current_context,
)


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class FakeUI:
    def __init__(self):
        self.choices = ["Collections 怎么用", None]
        self.shown = []

    def choose(self, title, items, **options):
        assert title == "CalDAV Assistant 使用向导"
        assert "Collections 怎么用" in items
        return self.choices.pop(0)

    def show(self, value):
        self.shown.append(value)


def make_manager(tmp_path):
    commands = CommandService(CommandRegistry())
    manager = ExtensionManager(
        commands,
        HookRegistry(),
        FakeSettings(),
        root=tmp_path / "extensions",
    )
    return manager, commands


def bundled_source():
    import caldav_assistant.bundled_extensions as bundled

    return Path(bundled.__file__).with_name("user_guide.py")


def test_user_guide_is_a_real_extension_and_supports_direct_topics(tmp_path):
    manager, commands = make_manager(tmp_path)
    record = manager.add(bundled_source())
    assert record.name == "user_guide"
    assert record.enabled is False

    loaded = manager.enable("user_guide")
    assert loaded.status == "loaded"
    assert commands.resolve("guide").source == "extension:user_guide"
    assert commands.resolve("tutorial").name == "guide"

    text = commands.run("guide", "collections")
    assert "Task collection" in text
    assert "VTODO" in text
    assert "Work log collection" in text

    work = commands.run("guide", "start")
    assert "start / pause / resume / done" in work
    assert "真实工作" in work


def test_interactive_guide_uses_public_ui_bricks_and_can_back_out(tmp_path):
    manager, commands = make_manager(tmp_path)
    manager.add(bundled_source())
    manager.enable("user_guide")

    ui = FakeUI()
    bind_current_context(SimpleNamespace(ui=ui))
    try:
        result = commands.run("guide")
    finally:
        clear_current_context()

    assert result is None
    assert len(ui.shown) == 1
    assert "Collection 可以理解为" in ui.shown[0]


def test_disabling_guide_removes_its_commands(tmp_path):
    manager, commands = make_manager(tmp_path)
    manager.add(bundled_source())
    manager.enable("user_guide")
    assert "guide" in commands.registry

    manager.disable("user_guide")
    assert "guide" not in commands.registry
    assert "tutorial" not in commands.registry
