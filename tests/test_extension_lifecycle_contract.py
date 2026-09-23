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


def _manager(tmp_path, settings, *, commands=None, hooks=None):
    commands = commands or CommandService(CommandRegistry())
    hooks = hooks or HookRegistry()
    manager = ExtensionManager(
        commands,
        hooks,
        settings,
        root=tmp_path / "extensions",
    )
    return manager, commands, hooks


def test_reload_of_disabled_extension_is_temporary_and_does_not_persist_enablement(tmp_path):
    settings = FakeSettings()
    manager, commands, hooks = _manager(tmp_path, settings)
    _write(
        manager.root / "demo.py",
        "from caldav_assistant.easy import command\n"
        "from caldav_assistant.api.v1.hooks import on\n"
        "@command('reload-probe')\n"
        "def reload_probe(): return 'loaded-now'\n"
        "@on('reload.probe')\n"
        "def probe(ctx): return None\n",
    )

    before = manager.get("demo")
    assert before.enabled is False
    assert before.status == "disabled"

    reloaded = manager.reload("demo")

    # reload() is a current-process test action. It loads code now but deliberately
    # does not change the persisted enablement preference.
    assert reloaded.status == "loaded"
    assert reloaded.enabled is False
    assert commands.run("reload-probe") == "loaded-now"
    assert len(hooks.entries("reload.probe")) == 1
    assert settings.get("extensions.enabled", {}) == {}

    # A fresh process/session sees the same persisted disabled preference and must
    # not auto-load the temporarily reloaded extension.
    restarted, restarted_commands, restarted_hooks = _manager(tmp_path, settings)
    restarted_record = restarted.get("demo")
    assert restarted_record.enabled is False
    assert restarted_record.status == "disabled"
    assert restarted.load_enabled() == ()
    assert "reload-probe" not in restarted_commands.registry
    assert restarted_hooks.entries("reload.probe") == ()
