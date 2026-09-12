import importlib.util
import os
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


def make(tmp_path):
    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    settings = FakeSettings()
    return (
        ExtensionManager(commands, hooks, settings, root=tmp_path / "extensions"),
        commands,
        hooks,
        settings,
    )


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_discover_enable_load_disable_and_persist_state(tmp_path):
    manager, commands, _, settings = make(tmp_path)
    write(
        manager.root / "demo.py",
        "from caldav_assistant.easy import command\n"
        "@command('urgent')\n"
        "def urgent():\n"
        "    return 'ok'\n",
    )
    assert [r.name for r in manager.discover()] == ["demo"]
    assert manager.enable("demo").status == "loaded"
    assert commands.run("urgent") == "ok"
    assert settings.get("extensions.enabled") == {"demo": True}
    assert manager.disable("demo").status == "disabled"
    assert "urgent" not in commands.registry


def test_failed_import_does_not_damage_core(tmp_path):
    manager, commands, _, _ = make(tmp_path)
    commands.register_builtin("today", lambda: "core")
    write(
        manager.root / "bad.py",
        "from caldav_assistant.easy import command\n"
        "@command('partial')\n"
        "def partial(): return 1\n"
        "raise RuntimeError('boom')\n",
    )
    record = manager.enable("bad")
    assert record.status == "error"
    assert commands.run("today") == "core"
    assert "partial" not in commands.registry


def test_reload_reads_same_size_source_even_when_mtime_matches_stale_pyc(tmp_path):
    manager, commands, _, _ = make(tmp_path)
    source = manager.root / "demo.py"
    v1 = (
        "from caldav_assistant.easy import command\n"
        "@command('fresh')\n"
        "def fresh():\n"
        "    return 'V1'\n"
    )
    v2 = v1.replace("V1", "V2")
    assert len(v1.encode()) == len(v2.encode())

    write(source, v1)
    assert manager.enable("demo").status == "loaded"
    assert commands.run("fresh") == "V1"

    cached = Path(importlib.util.cache_from_source(str(source)))
    assert cached.exists(), "test requires the ordinary timestamp .pyc path"
    original = source.stat()
    write(source, v2)
    os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert source.stat().st_size == original.st_size

    assert manager.reload("demo").status == "loaded"
    assert commands.run("fresh") == "V2"


def test_bundled_default_enabled_respects_explicit_user_disable(tmp_path):
    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    settings = FakeSettings()
    bundled = tmp_path / "bundled"
    write(
        bundled / "software_intro.py",
        "from caldav_assistant.api.v1.hooks import on\n"
        "@on('cli.repl.started')\n"
        "def intro(ctx): return 'hello'\n",
    )
    manager = ExtensionManager(
        commands,
        hooks,
        settings,
        root=tmp_path / "extensions",
        bundled_root=bundled,
        default_enabled=("software_intro",),
    )

    assert manager.get("software_intro").enabled is True
    assert manager.load_enabled()[0].status == "loaded"
    assert len(hooks.entries("cli.repl.started")) == 1

    assert manager.disable("software_intro").status == "disabled"
    assert settings.get("extensions.enabled") == {"software_intro": False}
    assert hooks.entries("cli.repl.started") == ()

    commands2 = CommandService(CommandRegistry())
    hooks2 = HookRegistry()
    restarted = ExtensionManager(
        commands2,
        hooks2,
        settings,
        root=tmp_path / "extensions",
        bundled_root=bundled,
        default_enabled=("software_intro",),
    )
    assert restarted.get("software_intro").enabled is False
    assert restarted.load_enabled() == ()