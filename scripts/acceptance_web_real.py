#!/usr/bin/env python3
"""HTTP human-path acceptance against real local Radicale and production Core.

The default mode uses an in-process dispatcher for sandboxes that cannot bind
AF_UNIX. With CALDAV_ASSISTANT_WEB_ACCEPTANCE_PRODUCTION=1 it launches the installed
web entrypoint and real background service over production IPC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
import json
import os
import secrets
import shutil
import site
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from caldav.davclient import DAVClient

from caldav_assistant.internal.settings.keys import (
    CALDAV_BASE_URL, CALDAV_CREDENTIALS, CALDAV_TASK_COLLECTION_URL,
    CALDAV_EVENT_COLLECTION_URL, CALDAV_WORKLOG_COLLECTION_URL,
    EXTENSIONS_ENABLED, NOTIFICATIONS_ENABLED, WORDPRESS_ENABLED,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import SQLiteKeyValueRepository, SQLiteStore
from caldav_assistant.internal.web.server import WebActions, make_handler


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http(url: str, *, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            content = response.read()
            return response.status, json.loads(content) if response.headers.get_content_type() == "application/json" else content
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> int:
    user_site = site.getusersitepackages()
    with tempfile.TemporaryDirectory(prefix="caldav-web-acceptance-") as folder:
        root = Path(folder)
        home = root / "home"; home.mkdir()
        os.environ["HOME"] = str(home)
        radicale_port = free_port()
        url = f"http://127.0.0.1:{radicale_port}/"
        storage = root / "radicale"; storage.mkdir()
        log = (root / "radicale.log").open("w")
        process = subprocess.Popen(
            [sys.executable, "-m", "radicale", "--config", "", "--server-hosts",
             f"127.0.0.1:{radicale_port}", "--storage-filesystem-folder", str(storage),
             "--auth-type", "none", "--logging-level", "warning"],
            stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((user_site, os.environ.get("PYTHONPATH", "")))},
        )
        server = None
        web_process = None
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url, timeout=.2).close()
                    break
                except Exception:
                    time.sleep(.1)
            else:
                raise RuntimeError(f"Radicale did not start (code {process.poll()}): {log.name}: {Path(log.name).read_text()[-2500:]}")

            caldav = DAVClient(url=url, username="test", password="test")
            principal = caldav.principal()
            tasks = principal.make_calendar(name="Tasks")
            work = principal.make_calendar(name="Assistant Work")
            now = datetime.now(timezone.utc).replace(microsecond=0)
            tasks.add_todo(uid="web-test-original", summary="Web acceptance original", status="NEEDS-ACTION", due=now + timedelta(days=1))
            tasks.add_event(uid="web-test-event", summary="Web acceptance event", dtstart=now + timedelta(hours=3), dtend=now + timedelta(hours=4))

            state = home / ".caldav-assistant"; state.mkdir()
            store = SQLiteStore(state / "assistant.sqlite3"); store.migrate()
            settings = SettingsService(SQLiteKeyValueRepository(store, "settings"))
            for key, value in {
                CALDAV_BASE_URL: url,
                CALDAV_CREDENTIALS: {"username": "test", "password": "test"},
                CALDAV_TASK_COLLECTION_URL: str(tasks.url),
                CALDAV_EVENT_COLLECTION_URL: str(tasks.url),
                CALDAV_WORKLOG_COLLECTION_URL: str(work.url),
                EXTENSIONS_ENABLED: {"software_intro": False, "wordpress_work_session_log": False},
                NOTIFICATIONS_ENABLED: False,
                WORDPRESS_ENABLED: False,
            }.items(): settings.set(key, value)

            web_port = free_port()
            base = f"http://127.0.0.1:{web_port}"
            if os.getenv("CALDAV_ASSISTANT_WEB_ACCEPTANCE_PRODUCTION") == "1":
                # Use the same installed entrypoint and AF_UNIX background bridge
                # as a user running caldav-assistant-web in a terminal.
                web_log = (root / "web.log").open("w")
                executable = shutil.which("caldav-assistant-web")
                if not executable:
                    raise RuntimeError("Install the package before the production web acceptance")
                web_process = subprocess.Popen(
                    [executable, "--port", str(web_port)],
                    env={**os.environ, "PYTHONPATH": os.pathsep.join((user_site, os.environ.get("PYTHONPATH", "")))},
                    stdout=web_log, stderr=subprocess.STDOUT,
                )
                for _ in range(100):
                    try:
                        if http(base + "/")[0] == 200:
                            break
                    except Exception:
                        time.sleep(.1)
                else:
                    raise RuntimeError(f"Installed web entrypoint did not start: {web_log.name}: {Path(web_log.name).read_text()[-2500:]}")
            else:
                from caldav_assistant.internal.bootstrap import build_service_application
                application = build_service_application()
                class DirectRuntime:
                    def call(self, method, **payload):
                        return application.background.dispatcher.handle(method, payload)
                app = SimpleNamespace(ctx=application.ctx, runtime=DirectRuntime())
                server = ThreadingHTTPServer(
                    ("127.0.0.1", web_port),
                    make_handler(WebActions(app), port=web_port, token=secrets.token_urlsafe(32)),
                )
                thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            token = http(base + "/api/token")[1]["token"]
            post_headers = {"Content-Type": "application/json", "X-Assistant-Token": token}

            code, page = http(base + "/")
            assert code == 200 and b"CalDAV Assistant" in page
            code, cold = http(base + "/api/snapshot")
            assert code == 200 and any(t["summary"] == "Web acceptance original" for t in cold["tasks"]), cold
            code, initial = http(base + "/api/snapshot?live=1")
            assert code == 200 and any(t["summary"] == "Web acceptance original" for t in initial["tasks"]), initial
            assert any(t["summary"] == "Web acceptance event" for t in initial["upcoming"]), initial
            print("PASS: local HTML and live Task/Event agenda")

            code, _ = http(base + "/api/task/create", data={"summary": "Blocked"}, headers={"Content-Type": "application/json"})
            assert code == 403
            code, _ = http(base + "/api/task/create", data={"summary": "Blocked"}, headers={**post_headers, "Origin": "https://example.org"})
            assert code == 403
            print("PASS: cross-origin and tokenless writes refused")

            code, created = http(base + "/api/task/create", data={"summary": "Web acceptance new", "due": "tomorrow"}, headers=post_headers)
            assert code == 200 and created["task"]["id"], created
            task_id = created["task"]["id"]
            code, edited = http(base + "/api/task/edit", data={"id": task_id, "summary": "Web acceptance edited", "due": "August5"}, headers=post_headers)
            assert code == 200 and edited["task"]["summary"] == "Web acceptance edited", edited
            print("PASS: create and edit Task with shared date parser")

            for action in ("start", "pause", "resume", "complete"):
                data = {"id": task_id, "action": action}
                if action == "start": data["minutes"] = 1
                code, result = http(base + "/api/task/action", data=data, headers=post_headers)
                assert code == 200 and result["success"], (action, code, result)
                code, view = http(base + "/api/snapshot?live=1")
                assert code == 200, (action, view)
                if action == "start":
                    assert view["current"]["id"] == task_id and view["work"]["state"] == "scheduled", view
                elif action == "pause":
                    assert view["current"] is None and task_id in view["paused_ids"], view
                elif action == "resume":
                    assert view["current"]["id"] == task_id, view
                else:
                    assert view["current"] is None and all(t["id"] != task_id for t in view["tasks"]), view
                print(f"PASS: {action} through Core")

            todo = [obj.get_icalendar_component() for obj in tasks.todos(include_completed=True)
                    if str(obj.get_icalendar_component().get("UID")) == task_id]
            assert len(todo) == 1 and str(todo[0].get("STATUS")) == "COMPLETED", todo
            print("PASS: real CalDAV VTODO completed; webpage lifecycle is authoritative")
            return 0
        finally:
            if server is not None:
                server.shutdown(); server.server_close()
            if web_process is not None:
                web_process.terminate()
                try: web_process.wait(timeout=5)
                except subprocess.TimeoutExpired: web_process.kill(); web_process.wait()
                from caldav_assistant.internal.bootstrap import build_cli_application
                runtime = build_cli_application().runtime
                if runtime.status().get("status") == "running":
                    runtime.stop(timeout=5)
                web_log.close()
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
