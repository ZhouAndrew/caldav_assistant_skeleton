from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api import AgendaItem, Task
from caldav_assistant.internal.cli import conversation_app, stale_startup_notice


def _module():
    return SimpleNamespace(conversation=conversation_app)


def test_startup_snapshot_text_warns_when_any_visible_fact_is_stale(monkeypatch):
    original = conversation_app._snapshot_text
    module = _module()
    monkeypatch.delattr(module, "_stale_startup_notice_installed", raising=False)

    stale_startup_notice.install(module)
    snapshot = conversation_app.StartupSnapshot(
        upcoming=(AgendaItem(Task(id="t1", summary="Offline task", stale=True)),),
        window_hours=24,
    )

    rendered = conversation_app._snapshot_text(snapshot)

    assert "Cached Task/Event data" in rendered
    assert "may be out of date" in rendered
    assert "Offline task" in rendered
    monkeypatch.setattr(conversation_app, "_snapshot_text", original)


def test_fresh_startup_snapshot_does_not_show_cache_warning(monkeypatch):
    original = conversation_app._snapshot_text
    module = _module()
    monkeypatch.delattr(module, "_stale_startup_notice_installed", raising=False)

    stale_startup_notice.install(module)
    snapshot = conversation_app.StartupSnapshot(
        recommended=Task(id="t1", summary="Fresh task"),
        window_hours=24,
    )

    rendered = conversation_app._snapshot_text(snapshot)

    assert "Cached Task/Event data" not in rendered
    monkeypatch.setattr(conversation_app, "_snapshot_text", original)
