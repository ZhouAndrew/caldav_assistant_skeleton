#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.server
import mimetypes
from pathlib import Path
import ssl
import sys
from urllib.parse import unquote, urlsplit


class UpdateHandler(http.server.BaseHTTPRequestHandler):
    server_version = "CalDAVAssistantUpdate/1.0"
    protocol_version = "HTTP/1.1"

    def _root(self) -> Path:
        return Path(self.server.document_root)  # type: ignore[attr-defined]

    def _file_for_request(self) -> Path | None:
        path = unquote(urlsplit(self.path).path)
        if not path.startswith("/experimental/"):
            return None
        relative = path.removeprefix("/").lstrip("/")
        candidate = (self._root() / relative).resolve()
        root = self._root().resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        return None

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str,
        cache_control: str = "no-store",
        head_only: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _serve(self, *, head_only: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send_bytes(
                200,
                b"ok\n",
                content_type="text/plain; charset=utf-8",
                head_only=head_only,
            )
            return

        target = self._file_for_request()
        if target is None:
            self._send_bytes(
                404,
                b"not found\n",
                content_type="text/plain; charset=utf-8",
                head_only=head_only,
            )
            return

        body = target.read_bytes()
        if target.name == "updates.json":
            content_type = "application/json; charset=utf-8"
            cache = "no-store, max-age=0"
        elif target.suffix.lower() == ".xpi":
            content_type = "application/x-xpinstall"
            cache = "public, max-age=31536000, immutable"
        else:
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            cache = "no-store"

        self._send_bytes(
            200,
            body,
            content_type=content_type,
            cache_control=cache,
            head_only=head_only,
        )

    def do_GET(self) -> None:  # noqa: N802
        self._serve(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(head_only=True)

    def log_message(self, fmt: str, *args: object) -> None:
        print(
            f"{self.address_string()} - [{self.log_date_time_string()}] {fmt % args}",
            file=sys.stderr,
            flush=True,
        )


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone HTTPS update server for CalDAV Assistant Thunderbird XPI"
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=17443)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    cert = args.cert.expanduser().resolve()
    key = args.key.expanduser().resolve()

    if not root.is_dir():
        raise SystemExit(f"Document root does not exist: {root}")
    if not cert.is_file() or not key.is_file():
        raise SystemExit("TLS certificate/key are missing")

    server = ThreadingHTTPServer((args.bind, args.port), UpdateHandler)
    server.document_root = root  # type: ignore[attr-defined]

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    print(
        f"CalDAV Assistant Thunderbird update server listening on "
        f"https://{args.bind}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
