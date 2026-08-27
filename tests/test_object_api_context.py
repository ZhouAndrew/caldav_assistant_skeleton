from __future__ import annotations

from caldav_assistant.api import AssistantContext


class Namespace:
    pass


def test_assistant_context_exposes_all_frozen_namespaces_without_wrapping_or_logic():
    values = [Namespace() for _ in range(12)]
    ctx = AssistantContext(*values)

    names = (
        "tasks", "events", "agenda", "reminders", "notifications", "wordpress",
        "ui", "time", "commands", "activity", "settings", "session",
    )

    assert tuple(ctx.__dataclass_fields__) == names
    for name, value in zip(names, values):
        assert getattr(ctx, name) is value


def test_context_accepts_realistic_service_or_proxy_shapes_by_structure():
    class Tasks:
        def list(self, **kw): return []
        def find(self, q, **kw): return None
        def get(self, x): return x
        def create(self, x, **kw): return None
        def update(self, x, **kw): return None
        def complete(self, x): return None
        def start(self, x): return None
        def pause(self, x): return None
        def resume(self, x): return None
        def delete(self, x): return None

    objects = [Tasks()] + [Namespace() for _ in range(11)]
    ctx = AssistantContext(*objects)
    assert ctx.tasks is objects[0]
