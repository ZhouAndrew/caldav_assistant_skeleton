from pathlib import Path

from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_reload_preserves_explicit_disabled_state_without_executing_extension(tmp_path):
    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    settings = FakeSettings()
    manager = ExtensionManager(
        commands,
        hooks,
        settings,
        root=tmp_path / "extensions",
    )
    _write(
        manager.root / "demo.py",
        "from caldav_assistant.easy import command\n"
        "from caldav_assistant.api.v1.hooks import on\n"
        "@command('reload-probe')\n"
        "def reload_probe(): return 'loaded'\n"
        "@on('reload.probe')\n"
        "def probe(ctx): return None\n",
    )

    discovered = manager.get("demo")
    assert discovered.enabled is False
    assert discovered.status == "disabled"

    reloaded = manager.reload("demo")

    assert reloaded.enabled is False
    assert reloaded.status == "disabled"
    assert "reload-probe" not in commands.registry
    assert hooks.entries("reload.probe") == ()
    assert settings.get("extensions.enabled", {}) == {}
