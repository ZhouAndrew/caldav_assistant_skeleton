from __future__ import annotations

import gc
import pytest

from caldav_assistant.internal.hook_event import EventBus, HookEvent


def test_hook_event_payload_is_immutable():
    event = HookEvent("task.completed", {"uid": "t-1"})
    assert event["uid"] == "t-1"
    with pytest.raises(TypeError):
        event.payload["uid"] = "x"


def test_priority_once_failure_and_reload_identity():
    bus = EventBus()
    seen = []

    def low(event): seen.append("low")
    def high(event): seen.append("high")
    def bad(event): raise RuntimeError("boom")

    bus.subscribe("task.completed", low, priority=0, owner="x")
    bus.subscribe("task.completed", high, priority=10, owner="y", once=True)
    bus.subscribe("task.completed", bad, priority=5, owner="z")
    report = bus.emit("task.completed", uid="1")
    assert seen == ["high", "low"]
    assert report.called == 3
    assert len(report.failures) == 1
    bus.emit("task.completed")
    assert seen == ["high", "low", "low"]


def test_dead_extension_handler_is_pruned():
    bus = EventBus()
    def make_handler():
        def handler(event): pass
        return handler
    handler = make_handler()
    bus.subscribe("task.completed", handler, owner="test.owner")
    del handler
    gc.collect()
    assert bus.listeners("task.completed") == 0
