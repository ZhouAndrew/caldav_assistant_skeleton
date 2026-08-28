from __future__ import annotations

from dataclasses import dataclass
import pytest

from caldav_assistant.api.v1.errors import AmbiguousError, UnavailableError, ValidationError
from caldav_assistant.internal.caldav.setup import CalDAVSetupService
from caldav_assistant.internal.settings.keys import CALDAV_CREDENTIALS


class Settings:
    def __init__(self):
        self.values = {}
    def get(self, key, default=None):
        return self.values.get(key, default)
    def set(self, key, value):
        self.values[key] = value
        return value
    def delete(self, key):
        self.values.pop(key, None)


@dataclass
class Resolved:
    base_url: str
    source: str = "saved"


class Discovery:
    def __init__(self):
        self.url = None
    def resolve(self):
        if self.url is None:
            raise UnavailableError("not configured")
        return Resolved(self.url)
    def get_base_url(self):
        if self.url is None:
            raise UnavailableError("not configured")
        return self.url
    def set_base_url(self, value):
        self.url = value.rstrip("/") + "/"
        return Resolved(self.url, "manual")


class AmbiguousDiscovery(Discovery):
    def resolve(self):
        raise AmbiguousError("choose one")
    def discover_candidates(self):
        return [
            "http://one.local:5232/",
            "http://two.local:5232/",
        ]


class Adapter:
    def __init__(self):
        self.credentials = None
        self.closed = 0
    def close(self):
        self.closed += 1
    def collections(self):
        return [
            {"name": "Tasks", "url": "/tasks/", "components": ["VTODO"]},
            {"name": "Calendar", "url": "/calendar/", "components": ["VEVENT"]},
        ]


def make():
    settings, discovery, adapter = Settings(), Discovery(), Adapter()
    return CalDAVSetupService(settings, discovery, adapter), settings, discovery, adapter


def test_status_never_returns_secret_material():
    service, settings, _, _ = make()
    settings.set(CALDAV_CREDENTIALS, {"username": "andrew", "password": "do-not-leak"})
    status = service.status()
    assert status["credentials_configured"] is True
    assert "do-not-leak" not in repr(status)
    assert "andrew" not in repr(status)


def test_server_credentials_clear_recycle_live_adapter():
    service, settings, _, adapter = make()
    assert service.set_base_url("http://andrew.local:5232")["base_url"].endswith("/")
    assert adapter.closed == 1
    assert service.set_credentials("andrew", "secret")["credentials_configured"] is True
    assert settings.get(CALDAV_CREDENTIALS)["username"] == "andrew"
    assert adapter.credentials["password"] == "secret"
    assert adapter.closed == 2
    assert service.clear_credentials()["credentials_configured"] is False
    assert settings.get(CALDAV_CREDENTIALS) is None
    assert adapter.credentials is None
    assert adapter.closed == 3


def test_connection_uses_collection_operation():
    service, _, _, _ = make()
    service.set_base_url("http://andrew.local:5232/")
    service.set_credentials("andrew", "secret")
    result = service.test_connection()
    assert result["ok"] is True
    assert result["collection_count"] == 2
    assert result["collections"][0]["name"] == "Tasks"


def test_empty_credentials_rejected():
    service, _, _, _ = make()
    with pytest.raises(ValidationError):
        service.set_credentials("", "secret")
    with pytest.raises(ValidationError):
        service.set_credentials("andrew", "")


def test_ambiguous_discovery_is_not_guessed_and_candidates_are_exposed():
    settings, adapter = Settings(), Adapter()
    service = CalDAVSetupService(settings, AmbiguousDiscovery(), adapter)
    status = service.status()
    assert status["base_url"] is None
    assert status["base_url_source"] == "ambiguous"
    assert status["discovered_candidates"] == [
        "http://one.local:5232/",
        "http://two.local:5232/",
    ]
