from caldav_assistant.internal import bootstrap
from caldav_assistant.internal.caldav import CollectionRoutingCalDAVAdapter


def test_background_sync_uses_same_role_routed_caldav_boundary_as_core(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_state_dir", lambda: tmp_path)

    app = bootstrap.build_service_application()

    assert isinstance(app.sync.adapter, CollectionRoutingCalDAVAdapter)
    # Core reads use stable offline fallback -> opt-in fast cache -> the same
    # role-routed authoritative adapter owned by SyncEngine.
    assert app.ctx.tasks.adapter.adapter.adapter is app.sync.adapter
    assert app.ctx.events.adapter.adapter.adapter is app.sync.adapter
