from __future__ import annotations

from typing import Any

from caldav_assistant.internal.caldav.library_adapter import (
    LibraryCalDAVAdapter,
)
from caldav_assistant.internal.caldav.transport import (
    CalDAVTransportSession,
)


class Provider:
    def __init__(self, url: str) -> None:
        self.url = url

    def get_base_url(self) -> str:
        return self.url


class FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _encoder(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    return {
        "username": str(value["username"]),
        "password": str(value["password"]),
    }


def _factory_log():
    created: list[FakeClient] = []

    def factory(**kwargs: Any) -> FakeClient:
        client = FakeClient(**kwargs)
        created.append(client)
        return client

    return created, factory


def test_transport_reuses_client_with_legacy_connection_options():
    provider = Provider("http://andrew.local:5232/")
    created, factory = _factory_log()
    session = CalDAVTransportSession(
        provider,
        {"username": "andrew", "password": "secret"},
        client_factory=factory,
        credential_encoder=_encoder,
        timeout=10.0,
    )

    first = session.client()
    second = session.client()

    assert first is second
    assert len(created) == 1
    assert first.kwargs == {
        "url": "http://andrew.local:5232/",
        "timeout": 10.0,
        "enable_rfc6764": False,
        "require_tls": False,
        "username": "andrew",
        "password": "secret",
    }


def test_transport_rebuilds_and_closes_when_base_url_changes():
    provider = Provider("http://old.example.test/")
    created, factory = _factory_log()
    session = CalDAVTransportSession(
        provider,
        None,
        client_factory=factory,
        credential_encoder=_encoder,
    )

    first = session.client()
    provider.url = "https://new.example.test/"
    second = session.client()

    assert second is not first
    assert first.close_calls == 1
    assert second.kwargs["url"] == "https://new.example.test/"
    assert len(created) == 2


def test_transport_detects_in_place_credential_change():
    provider = Provider("https://calendar.example.test/")
    credentials = {"username": "alice", "password": "one"}
    created, factory = _factory_log()
    session = CalDAVTransportSession(
        provider,
        credentials,
        client_factory=factory,
        credential_encoder=_encoder,
    )

    first = session.client()
    credentials["password"] = "two"
    second = session.client()

    assert second is not first
    assert first.close_calls == 1
    assert second.kwargs["password"] == "two"
    assert len(created) == 2


def test_explicit_probe_does_not_replace_cached_session():
    provider = Provider("https://calendar.example.test/")
    created, factory = _factory_log()
    session = CalDAVTransportSession(
        provider,
        {"username": "alice", "password": "one"},
        client_factory=factory,
        credential_encoder=_encoder,
    )

    cached = session.client()
    probe = session.new_client(
        "https://probe.example.test/",
        {"username": "probe", "password": "probe-secret"},
    )

    assert probe is not cached
    assert cached.close_calls == 0
    assert session.client() is cached
    assert probe.kwargs["url"] == "https://probe.example.test/"
    assert len(created) == 2


def test_library_adapter_keeps_old_credentials_api_and_reauthenticates():
    provider = Provider("http://andrew.local:5232/")
    created, factory = _factory_log()
    adapter = LibraryCalDAVAdapter(
        provider,
        {"username": "old-user", "password": "old-pass"},
        client_factory=factory,
    )

    first = adapter._client_now()
    adapter.credentials = {
        "username": "new-user",
        "password": "new-pass",
    }
    second = adapter._client_now()

    assert adapter.credentials == {
        "username": "new-user",
        "password": "new-pass",
    }
    assert second is not first
    assert first.close_calls == 1
    assert second.kwargs["username"] == "new-user"
    assert second.kwargs["password"] == "new-pass"
    assert len(created) == 2
