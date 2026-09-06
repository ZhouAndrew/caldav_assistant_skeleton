from caldav_assistant.internal import bootstrap
from caldav_assistant.internal.caldav import CollectionRoutingCalDAVAdapter


def test_background_sync_uses_same_role_routed_caldav_boundary_as_core(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_state_dir", lambda: tmp_path)

    app = bootstrap.build_service_application()

    assert isinstance(app.sync.adapter, CollectionRoutingCalDAVAdapter)
    assert app.ctx.tasks.adapter.adapter is app.sync.adapter
    assert app.ctx.events.adapter.adapter is app.sync.adapter
