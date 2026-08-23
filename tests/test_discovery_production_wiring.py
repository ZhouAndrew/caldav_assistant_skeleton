"""Regression test for the bug where FakeDiscoveryAdapter tests passed while
production bootstrap installed no real discovery adapter at all.
"""
from __future__ import annotations

from caldav_assistant.internal.bootstrap import _build_base_url_provider
from caldav_assistant.internal.discovery.adapters import MDNSCalDAVDiscoveryAdapter


class MemorySettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def test_production_base_url_provider_has_real_mdns_discovery(monkeypatch):
    monkeypatch.setattr(
        MDNSCalDAVDiscoveryAdapter,
        "discover_base_urls",
        lambda self: ["https://andrew.local/caldav"],
    )

    provider = _build_base_url_provider(MemorySettings())

    # This is deliberately an end-to-end wiring assertion: no FakeDiscoveryAdapter is
    # injected into ServerDiscovery by the test. The production factory must install
    # MDNSCalDAVDiscoveryAdapter itself, or this test fails.
    assert provider.get_base_url() == "https://andrew.local/caldav/"
