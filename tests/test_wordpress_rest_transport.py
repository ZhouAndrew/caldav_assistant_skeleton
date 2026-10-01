from __future__ import annotations

import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse

from caldav_assistant.internal.wordpress.rest_transport import ApplicationPasswordRESTAdapter


class WordPressFixture:
    def __init__(self):
        self.posts = {}
        self.next_post = 100
        self.username = "wp_user"
        self.password = "abcd1234"

    @property
    def auth(self):
        token = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        return "Basic " + token


def serve_wordpress(fixture):
    class Handler(BaseHTTPRequestHandler):
        def _auth(self):
            if self.headers.get("Authorization") != fixture.auth:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "code": "rest_not_logged_in",
                    "message": "You are not currently logged in.",
                }).encode())
                return False
            return True

        def _json(self, value, status=200):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._auth():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/wp-json/wp/v2/users/me":
                self._json({"id": 1, "name": "wp_user", "slug": "wp_user"})
                return
            if path == "/wp-json/wp/v2/posts":
                search = parse_qs(parsed.query).get("search", [""])[0].casefold()
                values = list(fixture.posts.values())
                if search:
                    values = [
                        item for item in values
                        if search in item["title"]["raw"].casefold()
                    ]
                self._json(values)
                return
            if path.startswith("/wp-json/wp/v2/posts/"):
                post_id = int(path.rsplit("/", 1)[-1])
                value = fixture.posts.get(post_id)
                if value is None:
                    self._json({"message": "missing"}, 404)
                else:
                    self._json(value)
                return
            self._json({"message": "unhandled"}, 404)

        def do_POST(self):
            if not self._auth():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw or b"{}")
            if path == "/wp-json/wp/v2/posts":
                fixture.next_post += 1
                post_id = fixture.next_post
                item = {
                    "id": post_id,
                    "status": body.get("status", "draft"),
                    "link": f"http://example.test/?p={post_id}",
                    "title": {
                        "raw": body.get("title", ""),
                        "rendered": body.get("title", ""),
                    },
                    "content": {
                        "raw": body.get("content", ""),
                        "rendered": body.get("content", ""),
                    },
                }
                fixture.posts[post_id] = item
                self._json(item, 201)
                return
            if path.startswith("/wp-json/wp/v2/posts/"):
                post_id = int(path.rsplit("/", 1)[-1])
                item = fixture.posts[post_id]
                if "content" in body:
                    item["content"] = {
                        "raw": body["content"],
                        "rendered": body["content"],
                    }
                if "title" in body:
                    item["title"] = {
                        "raw": body["title"],
                        "rendered": body["title"],
                    }
                if "status" in body:
                    item["status"] = body["status"]
                self._json(item)
                return
            self._json({"message": "unhandled"}, 404)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_application_password_rest_real_http_create_append_read_and_idempotency():
    fixture = WordPressFixture()
    server = serve_wordpress(fixture)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        adapter = ApplicationPasswordRESTAdapter(
            base_url,
            "wp_user",
            "abcd 1234",
            clock=lambda: datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc),
        )

        assert adapter.test_connection() is True

        first = adapter.create_log("First", _request_id="req-1", post_status="publish")
        second = adapter.create_log("Second", _request_id="req-2", post_status="publish")
        retry = adapter.create_log("Second", _request_id="req-2", post_status="publish")
        daily = adapter.read_daily_log()

        assert first["id"] == second["id"] == retry["id"]
        assert len(fixture.posts) == 1
        assert daily["id"] == first["id"]
        assert daily["title"] == "October 1 Thursday 2026"
        assert "First" in daily["content"]
        assert daily["content"].count("Second") == 1
        assert "caldav-assistant-log:req-1" in daily["content"]
        assert "caldav-assistant-log:req-2" in daily["content"]
    finally:
        server.shutdown()
        server.server_close()


def test_application_password_rest_rejects_bad_credentials_without_leaking_secret():
    fixture = WordPressFixture()
    server = serve_wordpress(fixture)
    try:
        adapter = ApplicationPasswordRESTAdapter(
            f"http://127.0.0.1:{server.server_port}",
            "wp_user",
            "wrong-secret",
        )
        assert adapter.test_connection() is False
    finally:
        server.shutdown()
        server.server_close()
