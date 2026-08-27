from __future__ import annotations

from pathlib import Path

import caldav_assistant.api as api
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.runtime.dispatcher import RuntimeDispatcher


class MemorySettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class PublicSettingsStub:
    def get(self, key, default=None):
        return default

    def set(self, key, value):
        return value

    def reset(self, key):
        return key

    def describe(self, key):
        return {"key": key}

    def list(self, category=None):
        return [{"category": category}]


def test_public_hook_event_exports_are_available():
    for name in (
        "EventBus",
        "HookEvent",
        "HookDispatchReport",
        "HookHandle",
        "emit",
        "off",
        "on",
        "unregister_owner",
    ):
        assert hasattr(api, name)


def test_extension_on_keeps_owner_aware_registry(tmp_path: Path):
    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    manager = ExtensionManager(commands, hooks, MemorySettings(), root=tmp_path / "ext")
    manager.root.mkdir(parents=True)
    (manager.root / "demo.py").write_text(
        "from caldav_assistant.api.v1 import on\n"
        "@on('task.completed')\n"
        "def completed(value):\n"
        "    return value + 1\n"
    )

    assert manager.enable("demo").status == "loaded"
    assert hooks.emit("task.completed", 4) == [5]
    assert len(hooks.entries("task.completed")) == 1
    manager.disable("demo")
    assert hooks.entries("task.completed") == ()


def test_runtime_dispatcher_exposes_validated_settings_routes():
    settings = PublicSettingsStub()

    class Namespace:
        pass

    ctx = Namespace()
    ctx.settings = settings

    # Supply placeholders for unrelated required routes.
    for namespace in (
        "tasks",
        "events",
        "agenda",
        "reminders",
        "notifications",
        "wordpress",
        "activity",
    ):
        obj = Namespace()
        setattr(ctx, namespace, obj)

    methods = {
        "tasks": ("list", "find", "get", "create", "update", "complete", "start", "pause", "resume", "delete"),
        "events": ("list", "find", "get", "create", "update", "delete"),
        "agenda": ("today", "range", "next", "overdue"),
        "reminders": ("list", "create", "snooze", "cancel"),
        "notifications": ("send",),
        "wordpress": ("log", "create_post", "update_post", "pending"),
        "activity": ("today", "for_task", "record"),
    }
    for namespace, names in methods.items():
        obj = getattr(ctx, namespace)
        for name in names:
            setattr(obj, name, lambda **kwargs: kwargs)

    dispatcher = RuntimeDispatcher(ctx)
    assert dispatcher.handle("settings.reset", {"key": "ui.locale"}) == "ui.locale"
    assert dispatcher.handle("settings.describe", {"key": "ui.locale"}) == {"key": "ui.locale"}
    assert dispatcher.handle("settings.list", {"category": "Language"}) == [{"category": "Language"}]
