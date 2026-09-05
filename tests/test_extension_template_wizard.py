from pathlib import Path
from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.extensions.cli import register_extension_cli_commands
from caldav_assistant.internal.settings.cli import SettingsActions


class FakeSettings:
    def __init__(self, **values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class FakeUI:
    def __init__(self, choices=(), texts=()):
        self.choices = list(choices)
        self.texts = list(texts)
        self.shown = []

    def choose(self, title, items, **_options):
        return self.choices.pop(0) if self.choices else None

    def ask_text(self, _prompt):
        return self.texts.pop(0) if self.texts else None

    def show(self, value):
        self.shown.append(value)


def make_manager(tmp_path):
    settings = FakeSettings()
    commands = CommandService(CommandRegistry())
    manager = ExtensionManager(
        commands,
        HookRegistry(),
        settings,
        root=tmp_path / "extensions",
    )
    register_extension_cli_commands(commands, manager)
    return manager, commands, settings


@pytest.mark.parametrize(
    ("template", "required"),
    [
        ("command", ("@command('demo')", "show(")),
        ("task", ("choose_task", "start(task)")),
        ("reminder", ("ask_datetime", "remind(")),
        ("daily", ("today()", "show(")),
        ("empty", ("@command('demo')", "pass")),
    ],
)
def test_extension_new_supports_small_runnable_easy_templates(tmp_path, template, required):
    manager, commands, _ = make_manager(tmp_path)

    result = commands.run("extension", "new", "demo", template)
    record = manager.get("demo")
    source = record.path.read_text(encoding="utf-8")

    assert record.enabled is False
    assert record.status == "disabled"
    assert len(source.splitlines()) < 25
    compile(source, str(record.path), "exec")
    assert "caldav_assistant.easy" in source
    assert "caldav_assistant.internal" not in source
    for text in required:
        assert text in source
    assert "Created typed Easy API extension demo" in result
    assert "extension enable demo" in result


def test_extension_new_keeps_old_detailed_template_when_kind_is_omitted(tmp_path):
    manager, commands, _ = make_manager(tmp_path)

    commands.run("extension", "new", "school")
    source = manager.get("school").path.read_text(encoding="utf-8")

    assert len(source.splitlines()) >= 100
    assert "Log a selected task" in source


def test_extension_new_rejects_unknown_template(tmp_path):
    manager, commands, _ = make_manager(tmp_path)

    with pytest.raises(ValidationError, match="Unknown extension template"):
        commands.run("extension", "new", "demo", "magic")

    assert not (manager.root / "demo.py").exists()


def test_settings_extension_creation_is_a_real_template_wizard(tmp_path):
    manager, commands, settings = make_manager(tmp_path)
    ui = FakeUI(
        choices=[
            "Task automation — choose and start a Task",
            "Keep disabled",
        ],
        texts=["homework"],
    )
    ctx = SimpleNamespace(ui=ui, settings=settings, commands=commands)

    SettingsActions(ctx)._create_extension_wizard()

    record = manager.get("homework")
    source = record.path.read_text(encoding="utf-8")
    assert record.enabled is False
    assert "choose_task" in source
    assert "start(task)" in source
    assert any("Created typed Easy API extension homework" in str(item) for item in ui.shown)


def test_settings_extension_wizard_can_enable_immediately(tmp_path):
    manager, commands, settings = make_manager(tmp_path)
    ui = FakeUI(
        choices=[
            "Command — add one small command",
            "Enable now",
        ],
        texts=["hello"],
    )
    ctx = SimpleNamespace(ui=ui, settings=settings, commands=commands)

    SettingsActions(ctx)._create_extension_wizard()

    assert manager.get("hello").status == "loaded"
    assert "hello" in commands.registry


def test_settings_notifications_explain_and_emit_the_real_logical_bell():
    settings = FakeSettings()
    ui = FakeUI(
        choices=[
            "How persistent acknowledgement works",
            "Test terminal bell",
        ]
    )
    ctx = SimpleNamespace(ui=ui, settings=settings, commands=CommandService(CommandRegistry()))

    SettingsActions(ctx)._notifications_panel()

    text = "\n".join(str(item) for item in ui.shown)
    assert "until you press Ctrl-C" in text
    assert "does not pause, complete, reschedule" in text
    assert "\a" in text


def test_settings_categories_surface_agenda_and_developer_tools():
    settings = FakeSettings()
    ui = FakeUI()
    ctx = SimpleNamespace(ui=ui, settings=settings, commands=CommandService(CommandRegistry()))

    text = SettingsActions(ctx).settings("categories")

    assert "Notifications" in text
    assert "Agenda" in text
    assert "Extensions" in text
    assert "Developer" in text
