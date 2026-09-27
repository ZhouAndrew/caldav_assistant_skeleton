#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import socket
import ssl
from urllib.parse import urlsplit


class LoopbackHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        raw = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def fetch(url: str, *, cafile: Path) -> tuple[int, bytes, dict[str, str]]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(f"Expected HTTPS URL, got {url!r}")
    context = ssl.create_default_context(cafile=str(cafile))
    conn = LoopbackHTTPSConnection(
        parsed.hostname,
        parsed.port or 443,
        context=context,
        timeout=5,
    )
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn.request("GET", path, headers={"Host": parsed.netloc})
        response = conn.getresponse()
        body = response.read()
        return response.status, body, {k.lower(): v for k, v in response.getheaders()}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca", required=True, type=Path)
    args = parser.parse_args()

    base = urlsplit(args.url)
    health = f"{base.scheme}://{base.netloc}/healthz"
    status, body, _ = fetch(health, cafile=args.ca)
    if status != 200 or body.strip() != b"ok":
        raise SystemExit(f"Health check failed: HTTP {status} {body!r}")

    status, body, headers = fetch(args.url, cafile=args.ca)
    if status != 200:
        raise SystemExit(f"Update manifest failed: HTTP {status}")
    if "application/json" not in headers.get("content-type", ""):
        raise SystemExit("Update manifest has wrong Content-Type")
    data = json.loads(body)
    updates = next(iter(data["addons"].values()))["updates"]
    xpi_url = str(updates[0]["update_link"])

    status, _, headers = fetch(xpi_url, cafile=args.ca)
    if status != 200:
        raise SystemExit(f"XPI failed: HTTP {status}")
    if headers.get("content-type") != "application/x-xpinstall":
        raise SystemExit("XPI has wrong Content-Type")

    print("Python HTTPS update server verification: OK")
    print(f"Manifest: {args.url}")
    print(f"XPI: {xpi_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
