from __future__ import annotations
from types import SimpleNamespace

from caldav_assistant.internal.runtime.dispatcher import RuntimeDispatcher
from caldav_assistant.internal.runtime.proxies import RemoteSettingsAPI


class Namespace:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def context():
    common = Namespace()
    return SimpleNamespace(
        tasks=common, events=common, agenda=common, reminders=common,
        notifications=common, wordpress=common, activity=common, settings=common,
    )


def test_dispatcher_explicit_internal_route():
    dispatcher = RuntimeDispatcher(context())
    dispatcher.register_internal("caldav.status", lambda: {"ok": True})
    assert dispatcher.handle("caldav.status", {}) == {"ok": True}


class Runtime:
    def __init__(self):
        self.calls = []
    def call(self, method, **payload):
        self.calls.append((method, payload or {}))
        return {"method": method, "payload": payload or {}}


def test_remote_settings_production_caldav_bridge():
    runtime = Runtime()
    settings = RemoteSettingsAPI(runtime)
    settings.caldav_status()
    assert runtime.calls[-1] == ("caldav.status", {})
    settings.set_caldav_credentials("andrew", "secret")
    assert runtime.calls[-1] == (
        "caldav.set_credentials",
        {"username": "andrew", "password": "secret"},
    )
    settings.test_caldav_connection()
    assert runtime.calls[-1] == ("caldav.test", {})


def test_production_cli_runtime_has_multi_request_caldav_budget():
    from caldav_assistant.internal.bootstrap import build_cli_application

    app = build_cli_application()
    assert app.runtime.request_timeout >= 30.0
    assert getattr(app.runtime.ipc, "timeout", 0.0) > app.runtime.request_timeout
