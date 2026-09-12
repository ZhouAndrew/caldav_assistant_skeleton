from caldav_assistant.internal import bootstrap
from caldav_assistant.internal.caldav import (
    CollectionRoutingCalDAVAdapter,
    ExperimentalCacheCalDAVAdapter,
    OfflineFallbackCalDAVAdapter,
)


def test_background_sync_uses_same_role_routed_caldav_boundary_as_core(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_state_dir", lambda: tmp_path)

    app = bootstrap.build_service_application()

    assert isinstance(app.sync.adapter, CollectionRoutingCalDAVAdapter)

    task_adapter = app.ctx.tasks.adapter
    event_adapter = app.ctx.events.adapter
    assert isinstance(task_adapter, OfflineFallbackCalDAVAdapter)
    assert isinstance(event_adapter, OfflineFallbackCalDAVAdapter)
    assert isinstance(task_adapter.adapter, ExperimentalCacheCalDAVAdapter)
    assert isinstance(event_adapter.adapter, ExperimentalCacheCalDAVAdapter)

    # Sync, healthy interactive reads, the optional fast cache and the stable
    # offline-read fallback all terminate at the same configured collection router.
    assert task_adapter.adapter.adapter is app.sync.adapter
    assert event_adapter.adapter.adapter is app.sync.adapter
