from __future__ import annotations
from types import SimpleNamespace

from caldav_assistant.internal.settings.cli import SettingsActions


class Settings:
    def __init__(self):
        self.calls = []
        self.status = {
            "base_url": "http://andrew.local:5232/",
            "base_url_configured": True,
            "credentials_configured": False,
        }
    def get(self, key, default=None):
        return self.status["base_url"] if key == "caldav.base_url" else default
    def caldav_status(self):
        return dict(self.status)
    def set_caldav_base_url(self, value):
        self.calls.append(("server", value))
        self.status["base_url"] = value.rstrip("/") + "/"
        self.status["base_url_configured"] = True
        return dict(self.status)
    def set_caldav_credentials(self, username, password):
        self.calls.append(("credentials", username, password))
        self.status["credentials_configured"] = True
        return dict(self.status)
    def test_caldav_connection(self):
        self.calls.append(("test",))
        return {"ok": True, "collection_count": 1}
    def caldav_collections(self):
        self.calls.append(("collections",))
        return [{"name": "Tasks"}]


class UI:
    def __init__(self):
        self.shown = []
    def show(self, value):
        self.shown.append(value)
    def ask_text(self, prompt):
        return "andrew"
    def ask_secret(self, prompt):
        return "secret"
    def choose(self, title, items):
        return None


def test_credentials_are_structured_and_never_render_password():
    settings, ui = Settings(), UI()
    actions = SettingsActions(SimpleNamespace(settings=settings, ui=ui))
    result = actions._set_caldav_credentials()
    assert settings.calls[-1] == ("credentials", "andrew", "secret")
    assert result["credentials_configured"] is True
    assert "secret" not in repr(ui.shown)


def test_connection_result_is_visible():
    settings, ui = Settings(), UI()
    actions = SettingsActions(SimpleNamespace(settings=settings, ui=ui))
    result = actions._test_caldav_connection()
    assert result["ok"] is True
    assert settings.calls[-1] == ("test",)


def test_single_discovered_server_can_be_selected_without_guessing():
    settings, ui = Settings(), UI()
    settings.status = {
        "base_url": None,
        "base_url_configured": False,
        "credentials_configured": False,
        "discovered_candidates": ["http://andrew.local:5232/"],
    }
    actions = SettingsActions(SimpleNamespace(settings=settings, ui=ui))
    result = actions._use_discovered_server()
    assert settings.calls[-1] == ("server", "http://andrew.local:5232/")
    assert result["base_url"] == "http://andrew.local:5232/"
