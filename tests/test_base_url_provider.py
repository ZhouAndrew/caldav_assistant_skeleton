from __future__ import annotations

import pytest

from caldav_assistant.api.v1.errors import (
    AmbiguousError,
    UnavailableError,
    ValidationError,
)
from caldav_assistant.internal.discovery import (
    BaseURLSource,
    ServerDiscovery,
    normalize_base_url,
)


class MemorySettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class FakeDiscoveryAdapter:
    def __init__(self, *urls: str):
        self.urls = urls

    def discover_base_urls(self):
        return self.urls


def test_manual_base_url_is_normalized_and_saved():
    settings = MemorySettings()
    provider = ServerDiscovery(settings)

    resolved = provider.set_base_url("  HTTPS://andrew.local/caldav  ")

    assert resolved.base_url == "https://andrew.local/caldav/"
    assert resolved.source is BaseURLSource.MANUAL
    assert provider.get_base_url() == "https://andrew.local/caldav/"


def test_saved_url_has_priority_over_discovery():
    settings = MemorySettings()
    provider = ServerDiscovery(
        settings,
        adapters=[FakeDiscoveryAdapter("https://other.local/dav")],
    )
    provider.set_base_url("https://andrew.local/caldav")

    resolved = provider.resolve()

    assert resolved.base_url == "https://andrew.local/caldav/"
    assert resolved.source is BaseURLSource.SAVED


def test_unique_discovery_candidate_is_returned_but_not_saved():
    settings = MemorySettings()
    provider = ServerDiscovery(
        settings,
        adapters=[FakeDiscoveryAdapter("https://caldav.local/dav")],
    )

    resolved = provider.resolve()

    assert resolved.base_url == "https://caldav.local/dav/"
    assert resolved.source is BaseURLSource.DISCOVERED
    assert settings.values == {}


def test_discovery_candidates_are_deduplicated_after_normalization():
    settings = MemorySettings()
    provider = ServerDiscovery(
        settings,
        adapters=[
            FakeDiscoveryAdapter(
                "https://a.local/dav",
                "https://a.local/dav/",
            )
        ],
    )

    assert provider.discover_candidates() == ["https://a.local/dav/"]


def test_multiple_candidates_require_user_selection():
    provider = ServerDiscovery(
        MemorySettings(),
        adapters=[FakeDiscoveryAdapter("https://a.local/", "https://b.local/")],
    )

    with pytest.raises(AmbiguousError):
        provider.get_base_url()


def test_missing_configuration_requires_setup():
    with pytest.raises(UnavailableError):
        ServerDiscovery(MemorySettings()).get_base_url()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "andrew.local/caldav",
        "ftp://andrew.local/caldav",
        "https://user:secret@andrew.local/caldav/",
        "https://andrew.local/caldav/?x=1",
        "https://andrew.local/caldav/#fragment",
        "https://andrew.local:99999/caldav/",
    ],
)
def test_invalid_base_urls_are_rejected(value):
    with pytest.raises(ValidationError):
        normalize_base_url(value)
