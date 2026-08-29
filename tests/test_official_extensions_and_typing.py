from __future__ import annotations

import json
from pathlib import Path
from typing import get_type_hints

import caldav_assistant
from caldav_assistant.api import AssistantContext, EventsAPI, TasksAPI
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


def make_manager(tmp_path: Path):
    commands = CommandService(CommandRegistry())
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "software_intro.py").write_text(
        '"""test official extension"""\n',
        encoding="utf-8",
    )
    manager = ExtensionManager(
        commands,
        HookRegistry(),
        FakeSettings(),
        root=tmp_path / "user-extensions",
        bundled_root=bundled,
        default_enabled=("software_intro",),
    )
    register_extension_cli_commands(commands, manager)
    return manager, commands


def test_official_extensions_are_distinguished_and_manageable(tmp_path):
    manager, commands = make_manager(tmp_path)

    listing = commands.run("extensions")
    official = commands.run("extension", "official")
    info = commands.run("extension", "info", "software_intro")

    assert "Official bundled extensions" in listing
    assert "[official] software_intro" in listing
    assert "software_intro" in official
    assert "Origin: Official" in info
    assert "Default: enabled" in info
    assert "application updates" in info

    disabled = commands.run("extension", "disable", "software_intro")
    assert "disabled" in disabled
    assert manager.settings.get("extensions.enabled") == {"software_intro": False}

    reset = commands.run("extension", "reset", "software_intro")
    assert "packaged default" in reset
    assert manager.get("software_intro").enabled is True
    assert manager.settings.get("extensions.enabled") == {"software_intro": True}


def test_user_extension_is_not_mislabelled_as_official(tmp_path):
    manager, commands = make_manager(tmp_path)
    commands.run("extension", "new", "school")

    listing = commands.run("extensions")
    user = commands.run("extension", "user")
    info = commands.run("extension", "info", "school")

    assert "[user] school" in listing
    assert "school" in user
    assert "Origin: User extension" in info
    assert "extension dev" in info


def test_extension_dev_creates_non_destructive_vscode_pylance_settings(tmp_path):
    manager, commands = make_manager(tmp_path)

    first = commands.run("extension", "dev")
    settings_path = manager.root / ".vscode" / "settings.json"
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["python.analysis.typeCheckingMode"] == "basic"
    assert settings["python.analysis.autoImportCompletions"] is True
    assert "py.typed" in first

    settings_path.write_text('{"custom": true}\n', encoding="utf-8")
    second = commands.run("extension", "dev")
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"custom": True}
    assert "left unchanged" in second


def test_generated_extension_template_is_typed_for_editor_help(tmp_path):
    manager, commands = make_manager(tmp_path)
    commands.run("extension", "new", "school")

    source = (manager.root / "school.py").read_text(encoding="utf-8")
    assert "from caldav_assistant.api import Agenda" in source
    assert "def run() -> None:" in source
    assert "items: Agenda = today()" in source
    assert "PEP 561" in source


def test_package_exposes_pep561_marker_easy_stub_and_typed_context_protocols():
    package_root = Path(caldav_assistant.__file__).resolve().parent
    assert (package_root / "py.typed").is_file()
    easy_stub = (package_root / "easy.pyi").read_text(encoding="utf-8")
    assert "def tasks(**filters: Any) -> list[Task]" in easy_stub
    assert "def start(task: Task | str) -> ActionResult | None" in easy_stub
    assert "def add_event(summary: str, **fields: Any) -> ActionResult" in easy_stub

    hints = get_type_hints(AssistantContext)
    assert hints["tasks"] is TasksAPI
    assert hints["events"] is EventsAPI


def test_pyproject_packages_typing_files_for_installed_editor_use():
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = project.read_text(encoding="utf-8")
    assert '[tool.setuptools.package-data]' in text
    assert '"py.typed"' in text
    assert '"*.pyi"' in text
