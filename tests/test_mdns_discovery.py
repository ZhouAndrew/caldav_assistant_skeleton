from __future__ import annotations

import struct

from caldav_assistant.internal.discovery.adapters.mdns import MDNSCalDAVDiscoveryAdapter


def _name(value: str) -> bytes:
    out = bytearray()
    for label in value.rstrip(".").split("."):
        raw = label.encode()
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def _rr(owner: str, rtype: int, rdata: bytes) -> bytes:
    return _name(owner) + struct.pack("!HHIH", rtype, 1, 120, len(rdata)) + rdata


def _response(service_type: str, *, host: str, port: int, path: str | None) -> bytes:
    instance = f"Home CalDAV.{service_type}"
    ptr = _rr(service_type, 12, _name(instance))
    srv = _rr(instance, 33, struct.pack("!HHH", 0, 0, port) + _name(host))
    records = [ptr, srv]
    if path is not None:
        item = f"path={path}".encode()
        records.append(_rr(instance, 16, bytes([len(item)]) + item))
    return struct.pack("!HHHHHH", 0, 0x8400, 0, len(records), 0, 0) + b"".join(records)


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    def query(self, service_type: str, timeout: float):
        self.queries.append(service_type)
        return self.responses.get(service_type, [])


def test_mdns_discovers_tls_service_and_uses_txt_path():
    secure = "_caldavs._tcp.local."
    transport = FakeTransport(
        {secure: [_response(secure, host="andrew.local.", port=443, path="/caldav")]}
    )

    adapter = MDNSCalDAVDiscoveryAdapter(transport=transport)

    assert adapter.discover_base_urls() == ["https://andrew.local/caldav"]
    assert transport.queries == [secure]


def test_mdns_uses_well_known_when_txt_path_is_missing():
    secure = "_caldavs._tcp.local."
    transport = FakeTransport(
        {secure: [_response(secure, host="emma.local.", port=8443, path=None)]}
    )

    adapter = MDNSCalDAVDiscoveryAdapter(transport=transport)

    assert adapter.discover_base_urls() == [
        "https://emma.local:8443/.well-known/caldav"
    ]


def test_mdns_falls_back_to_plain_caldav_only_when_tls_not_found():
    secure = "_caldavs._tcp.local."
    plain = "_caldav._tcp.local."
    transport = FakeTransport(
        {plain: [_response(plain, host="legacy.local.", port=80, path="/dav")]}
    )

    adapter = MDNSCalDAVDiscoveryAdapter(transport=transport)

    assert adapter.discover_base_urls() == ["http://legacy.local/dav"]
    assert transport.queries == [secure, plain]
