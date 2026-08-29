from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.runtime.proxies import RemoteSettingsAPI
from caldav_assistant.internal.settings.cli import SettingsActions
from caldav_assistant.internal.settings.keys import EXPERIMENTAL_FAST_QUERY_CACHE


class FakeUI:
    def __init__(self, choices=()):
        self.choices = list(choices)
        self.menus = []
        self.shown = []

    def choose(self, title, items):
        self.menus.append((title, list(items)))
        if not self.choices:
            return None
        return self.choices.pop(0)

    def show(self, value):
        self.shown.append(str(value))


class FakeSettings:
    def __init__(self):
        self.values = {EXPERIMENTAL_FAST_QUERY_CACHE: False}
        self.refresh_calls = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value

    def list(self, category=None):
        return []

    def _experimental_cache_status(self):
        return {
            "enabled": self.values[EXPERIMENTAL_FAST_QUERY_CACHE],
            "snapshot_available": True,
            "task_count": 3,
            "event_count": 2,
            "synced_at": "2026-08-29T08:00:00+00:00",
            "cache_updated_at": None,
            "cache_update_reason": None,
            "read_counts": {"cache": 4, "caldav": 1},
            "recent_reads": [
                {
                    "operation": "tasks.list",
                    "source": "cache",
                    "reason": "snapshot-hit",
                }
            ],
            "sync_status": {
                "state": "ok",
                "effective_mode": "full-scan",
            },
        }

    def _experimental_cache_refresh(self):
        self.refresh_calls += 1
        return {
            "state": "ok",
            "task_count": 3,
            "event_count": 2,
        }


def make_actions(choices=()):
    ui = FakeUI(choices)
    settings = FakeSettings()
    ctx = SimpleNamespace(ui=ui, settings=settings)
    return SettingsActions(ctx), ui, settings


def test_settings_menu_exposes_experimental_and_operates_cache_panel():
    actions, ui, settings = make_actions(
        [
            "Experimental",
            "Fast query cache (experimental): Off",
            "On",
            "Cache status",
            "Refresh cache now",
            None,
            None,
        ]
    )

    actions.interactive()

    assert "Experimental" in ui.menus[0][1]
    assert settings.values[EXPERIMENTAL_FAST_QUERY_CACHE] is True
    assert settings.refresh_calls == 1
    assert any("tasks.list → cache (snapshot-hit)" in text for text in ui.shown)
    assert any("Cache refreshed from authoritative CalDAV" in text for text in ui.shown)


def test_settings_cache_status_is_human_readable_and_transparent():
    actions, _, _ = make_actions()

    text = actions.settings("cache", "status")

    assert "Fast query cache: Off" in text
    assert "Snapshot: Available (3 task(s), 2 event(s))" in text
    assert "Verified from CalDAV: 2026-08-29T08:00:00+00:00" in text
    assert "Reads since background service start: cache=4, CalDAV=1" in text
    assert "tasks.list → cache (snapshot-hit)" in text


def test_settings_cache_refresh_forces_authoritative_sync_summary():
    actions, _, settings = make_actions()

    text = actions.settings("cache", "refresh")

    assert settings.refresh_calls == 1
    assert text == "✓ Cache refreshed from authoritative CalDAV: 3 task(s), 2 event(s)."


def test_settings_categories_includes_experimental():
    actions, _, _ = make_actions()

    categories = actions.settings("categories").splitlines()

    assert categories[-1] == "Experimental"


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {"method": method}


def test_cache_diagnostics_use_private_runtime_routes_not_public_settings_methods():
    runtime = FakeRuntime()
    api = RemoteSettingsAPI(runtime)

    status = api._experimental_cache_status()
    refresh = api._experimental_cache_refresh()

    assert status["method"] == "experimental.cache.status"
    assert refresh["method"] == "experimental.cache.refresh"
    assert runtime.calls == [
        ("experimental.cache.status", {}),
        ("experimental.cache.refresh", {}),
    ]
