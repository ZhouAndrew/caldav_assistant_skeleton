"""mDNS / DNS-SD CalDAV discovery adapter."""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any, Callable


_SECURE = "_caldavs._tcp.local."
_PLAIN = "_caldav._tcp.local."
_WELL_KNOWN = "/.well-known/caldav"


class _AvahiTransport:
    """Production transport using avahi-browse."""

    def __init__(
        self,
        *,
        runner: Callable[..., Any] | None = None,
        executable: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        self._runner = runner or subprocess.run
        self._executable = (
            executable
            or shutil.which("avahi-browse")
            or "avahi-browse"
        )
        self._timeout = timeout

    @staticmethod
    def _unquote_txt(value: str) -> str:
        value = value.strip()

        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]

        return value.replace(r"\032", " ").replace(r'\"', '"')

    def browse(self, service_type: str) -> list[dict[str, Any]]:
        avahi_type = service_type.removesuffix(".local.")

        try:
            result = self._runner(
                [self._executable, "-rpt", avahi_type],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (
            FileNotFoundError,
            subprocess.SubprocessError,
            OSError,
        ):
            return []

        records: list[dict[str, Any]] = []

        for raw_line in (getattr(result, "stdout", "") or "").splitlines():
            line = raw_line.strip()

            if not line.startswith("="):
                continue

            parts = line.split(";")

            # avahi-browse -p:
            #
            # =;iface;proto;name;type;domain;host;address;port;txt...
            if len(parts) < 9:
                continue

            if parts[4] != avahi_type:
                continue

            try:
                port = int(parts[8])
            except ValueError:
                continue

            path: str | None = None

            for field in parts[9:]:
                txt = self._unquote_txt(field)

                match = re.search(
                    r"(?:^|[\s\"])(?:path)=([^\"\s]+)",
                    txt,
                    re.IGNORECASE,
                )

                if match:
                    path = match.group(1)
                    break

            records.append(
                {
                    "host": parts[6],
                    "port": port,
                    "path": path,
                }
            )

        return records


def _decode_dns_name(
    packet: bytes,
    offset: int,
) -> tuple[str, int]:
    """Decode a DNS name, including compression pointers."""

    labels: list[str] = []
    jumped = False
    next_offset = offset
    seen_pointers: set[int] = set()

    while True:
        if offset >= len(packet):
            raise ValueError("truncated DNS name")

        length = packet[offset]

        if length == 0:
            offset += 1

            if not jumped:
                next_offset = offset

            break

        # DNS compression pointer: 11xxxxxx xxxxxxxx
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("truncated DNS compression pointer")

            pointer = (
                ((length & 0x3F) << 8)
                | packet[offset + 1]
            )

            if pointer in seen_pointers:
                raise ValueError("DNS compression loop")

            seen_pointers.add(pointer)

            if not jumped:
                next_offset = offset + 2
                jumped = True

            offset = pointer
            continue

        if length & 0xC0:
            raise ValueError("invalid DNS label")

        offset += 1
        end = offset + length

        if end > len(packet):
            raise ValueError("truncated DNS label")

        labels.append(
            packet[offset:end].decode(
                "utf-8",
                errors="replace",
            )
        )

        offset = end

        if not jumped:
            next_offset = offset

    return ".".join(labels) + ".", next_offset


def _parse_dns_packet(
    packet: bytes,
) -> list[dict[str, Any]]:
    """Parse PTR, SRV and TXT resource records from one DNS response."""

    if len(packet) < 12:
        return []

    try:
        (
            _ident,
            _flags,
            question_count,
            answer_count,
            authority_count,
            additional_count,
        ) = struct.unpack(
            "!HHHHHH",
            packet[:12],
        )
    except struct.error:
        return []

    offset = 12

    try:
        # Skip questions.
        for _ in range(question_count):
            _, offset = _decode_dns_name(
                packet,
                offset,
            )

            if offset + 4 > len(packet):
                return []

            offset += 4

        result: list[dict[str, Any]] = []

        total_records = (
            answer_count
            + authority_count
            + additional_count
        )

        for _ in range(total_records):
            owner, offset = _decode_dns_name(
                packet,
                offset,
            )

            if offset + 10 > len(packet):
                return result

            (
                record_type,
                record_class,
                ttl,
                data_length,
            ) = struct.unpack(
                "!HHIH",
                packet[offset : offset + 10],
            )

            offset += 10

            data_start = offset
            data_end = data_start + data_length

            if data_end > len(packet):
                return result

            record: dict[str, Any] = {
                "owner": owner,
                "type": record_type,
                "class": record_class,
                "ttl": ttl,
            }

            # PTR
            if record_type == 12:
                target, _ = _decode_dns_name(
                    packet,
                    data_start,
                )

                record["target"] = target

            # SRV
            elif record_type == 33:
                if data_length >= 6:
                    (
                        priority,
                        weight,
                        port,
                    ) = struct.unpack(
                        "!HHH",
                        packet[
                            data_start : data_start + 6
                        ],
                    )

                    target, _ = _decode_dns_name(
                        packet,
                        data_start + 6,
                    )

                    record.update(
                        {
                            "priority": priority,
                            "weight": weight,
                            "port": port,
                            "target": target,
                        }
                    )

            # TXT
            elif record_type == 16:
                txt_items: list[str] = []

                position = data_start

                while position < data_end:
                    length = packet[position]
                    position += 1

                    item_end = position + length

                    if item_end > data_end:
                        break

                    txt_items.append(
                        packet[
                            position:item_end
                        ].decode(
                            "utf-8",
                            errors="replace",
                        )
                    )

                    position = item_end

                record["txt"] = txt_items

            result.append(record)

            offset = data_end

        return result

    except (
        ValueError,
        struct.error,
        IndexError,
    ):
        return []


def _urls_from_dns_packet(
    packet: bytes,
    *,
    service_type: str,
    secure: bool,
) -> list[str]:
    """Build CalDAV candidate URLs from a raw DNS-SD response."""

    records = _parse_dns_packet(packet)

    # PTR:
    # _caldavs._tcp.local.
    #       ->
    # Home CalDAV._caldavs._tcp.local.
    instances: list[str] = []

    for record in records:
        if record.get("type") != 12:
            continue

        if record.get("owner") != service_type:
            continue

        target = record.get("target")

        if target:
            instances.append(str(target))

    urls: list[str] = []

    for instance in instances:
        srv_record: dict[str, Any] | None = None
        txt_record: dict[str, Any] | None = None

        for record in records:
            if record.get("owner") != instance:
                continue

            if record.get("type") == 33:
                srv_record = record

            elif record.get("type") == 16:
                txt_record = record

        if srv_record is None:
            continue

        host = srv_record.get("target")
        port = srv_record.get("port")

        if not host or port is None:
            continue

        try:
            port = int(port)
        except (TypeError, ValueError):
            continue

        if not 1 <= port <= 65535:
            continue

        host = str(host).rstrip(".")

        path: str | None = None

        if txt_record is not None:
            for item in txt_record.get("txt", []):
                if item.lower().startswith("path="):
                    path = item[5:]
                    break

        if not path:
            path = _WELL_KNOWN

        if not path.startswith("/"):
            path = "/" + path

        if path != "/":
            path = path.rstrip("/")

        scheme = "https" if secure else "http"

        default_port = (
            (secure and port == 443)
            or (not secure and port == 80)
        )

        if default_port:
            authority = host
        else:
            authority = f"{host}:{port}"

        urls.append(
            f"{scheme}://{authority}{path}"
        )

    return urls


class MDNSCalDAVDiscoveryAdapter:
    """Discover CalDAV endpoints using DNS-SD."""

    def __init__(
        self,
        transport: Any | None = None,
        *,
        runner: Callable[..., Any] | None = None,
        executable: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        self._timeout = timeout

        self._transport = transport or _AvahiTransport(
            runner=runner,
            executable=executable,
            timeout=timeout,
        )

    def _query(
        self,
        service_type: str,
    ) -> Sequence[Any]:
        """Query one DNS-SD service type."""

        query = getattr(
            self._transport,
            "query",
            None,
        )

        if callable(query):
            return (
                query(
                    service_type,
                    self._timeout,
                )
                or ()
            )

        browse = getattr(
            self._transport,
            "browse",
            None,
        )

        if callable(browse):
            return browse(service_type) or ()

        raise TypeError(
            "mDNS transport must provide "
            "query(service_type, timeout) "
            "or browse(service_type)"
        )

    @staticmethod
    def _url_from_mapping(
        record: Mapping[str, Any],
        *,
        secure: bool,
    ) -> str | None:
        """Handle production Avahi dictionary records."""

        host = (
            record.get("host")
            or record.get("hostname")
            or record.get("target")
        )

        port = record.get("port")

        if not host or port is None:
            return None

        try:
            port = int(port)
        except (TypeError, ValueError):
            return None

        if not 1 <= port <= 65535:
            return None

        host = str(host).rstrip(".")

        path = record.get("path")

        if not path:
            path = _WELL_KNOWN

        path = str(path)

        if not path.startswith("/"):
            path = "/" + path

        if path != "/":
            path = path.rstrip("/")

        scheme = "https" if secure else "http"

        default_port = (
            (secure and port == 443)
            or (not secure and port == 80)
        )

        authority = (
            host
            if default_port
            else f"{host}:{port}"
        )

        return f"{scheme}://{authority}{path}"

    def _urls_for(
        self,
        service_type: str,
        *,
        secure: bool,
    ) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        for response in self._query(service_type):

            # Test transport / raw mDNS transport:
            # complete DNS response packet.
            if isinstance(
                response,
                (bytes, bytearray, memoryview),
            ):
                candidates = _urls_from_dns_packet(
                    bytes(response),
                    service_type=service_type,
                    secure=secure,
                )

            # Production Avahi transport.
            elif isinstance(response, Mapping):
                url = self._url_from_mapping(
                    response,
                    secure=secure,
                )

                candidates = (
                    [url]
                    if url is not None
                    else []
                )

            else:
                candidates = []

            for url in candidates:
                if url in seen:
                    continue

                seen.add(url)
                urls.append(url)

        return urls

    def discover_base_urls(self) -> Sequence[str]:
        """Return discovered CalDAV Base URL candidates."""

        # Prefer TLS.
        secure_urls = self._urls_for(
            _SECURE,
            secure=True,
        )

        if secure_urls:
            return secure_urls

        # Only fall back to plaintext when no TLS service exists.
        return self._urls_for(
            _PLAIN,
            secure=False,
        )

    # Convenience alias for discovery callers.
    def discover(self) -> Sequence[str]:
        return self.discover_base_urls()