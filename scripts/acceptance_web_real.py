#!/usr/bin/env python3
"""Real one-command Web acceptance against a real local Radicale server.

This intentionally exercises the installed user path:
  caldav-assistant web --no-open
  -> first-run web setup
  -> live Task/Event reads
  -> create/edit/start/pause/resume/complete
  -> authoritative CalDAV verification
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
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


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http(url: str, *, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            content = response.read()
            if response.headers.get_content_type() == "application/json":
                return response.status, json.loads(content)
            return response.status, content
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def wait_http(url: str, process: subprocess.Popen, log_path: Path) -> None:
    for _ in range(120):
        if process.poll() is not None:
            break
        try:
            if http(url)[0] == 200:
                return
        except Exception:
            time.sleep(0.1)
    tail = log_path.read_text(errors="replace")[-3500:] if log_path.exists() else ""
    raise RuntimeError(
        f"process did not become ready (code={process.poll()}): {log_path}\n{tail}"
    )


def main() -> int:
    user_site = site.getusersitepackages()
    with tempfile.TemporaryDirectory(prefix="caldav-web-acceptance-") as folder:
        root = Path(folder)
        home = root / "home"
        home.mkdir()
        os.environ["HOME"] = str(home)

        radicale_port = free_port()
        radicale_url = f"http://127.0.0.1:{radicale_port}/"
        storage = root / "radicale"
        storage.mkdir()
        radicale_log = root / "radicale.log"
        radicale_stream = radicale_log.open("w")
        radicale = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "radicale",
                "--config",
                "",
                "--server-hosts",
                f"127.0.0.1:{radicale_port}",
                "--storage-filesystem-folder",
                str(storage),
                "--auth-type",
                "none",
                "--logging-level",
                "warning",
            ],
            stdout=radicale_stream,
            stderr=subprocess.STDOUT,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    (user_site, os.environ.get("PYTHONPATH", ""))
                ),
            },
        )

        web = None
        web_stream = None
        try:
            wait_http(radicale_url, radicale, radicale_log)

            caldav = DAVClient(url=radicale_url, username="test", password="test")
            principal = caldav.principal()
            tasks = principal.make_calendar(name="Tasks")
            work = principal.make_calendar(name="Assistant Work")
            now = datetime.now(timezone.utc).replace(microsecond=0)
            tasks.add_todo(
                uid="web-test-original",
                summary="Web acceptance original",
                status="NEEDS-ACTION",
                due=now + timedelta(days=1),
            )
            tasks.add_event(
                uid="web-test-event",
                summary="Web acceptance event",
                dtstart=now + timedelta(hours=3),
                dtend=now + timedelta(hours=4),
            )

            executable = shutil.which("caldav-assistant")
            if not executable:
                raise RuntimeError("Install the package before web acceptance")

            web_port = free_port()
            base = f"http://127.0.0.1:{web_port}"
            web_log = root / "web.log"
            web_stream = web_log.open("w")
            web = subprocess.Popen(
                [
                    executable,
                    "web",
                    "--no-open",
                    "--port",
                    str(web_port),
                ],
                env={
                    **os.environ,
                    "PYTHONPATH": os.pathsep.join(
                        (user_site, os.environ.get("PYTHONPATH", ""))
                    ),
                },
                stdout=web_stream,
                stderr=subprocess.STDOUT,
            )
            wait_http(base + "/api/health", web, web_log)

            code, page = http(base + "/")
            assert code == 200 and b"CalDAV Assistant" in page
            assert b"setup-form" in page
            print("PASS: one-command installed web entrypoint serves first-run UI")

            code, setup = http(base + "/api/setup/status")
            assert code == 200 and setup["ready"] is False, setup
            token = http(base + "/api/token")[1]["token"]
            post_headers = {
                "Content-Type": "application/json",
                "X-Assistant-Token": token,
            }

            code, configured = http(
                base + "/api/setup/connect",
                data={
                    "base_url": radicale_url,
                    "username": "test",
                    "password": "test",
                },
                headers=post_headers,
            )
            assert code == 200 and configured["ready"] is True, configured
            assert configured["connection_ok"] is True
            assert configured["collection_count"] >= 2
            assert configured["roles"]["task"]
            assert configured["roles"]["event"]
            assert configured["roles"]["worklog"]
            assert configured["roles"]["worklog"] != configured["roles"]["task"]
            assert configured["credentials_configured"] is True
            print("PASS: first-run CalDAV setup saves credentials, tests, and assigns collection roles")

            code, initial = http(base + "/api/snapshot?live=1")
            assert code == 200, initial
            assert any(
                item["summary"] == "Web acceptance original"
                for item in initial["tasks"]
            ), initial
            assert any(
                item["summary"] == "Web acceptance event"
                for item in initial["upcoming"]
            ), initial
            print("PASS: live Task/Event agenda appears after setup without restart")

            code, _ = http(
                base + "/api/task/create",
                data={"summary": "Blocked"},
                headers={"Content-Type": "application/json"},
            )
            assert code == 403
            code, _ = http(
                base + "/api/task/create",
                data={"summary": "Blocked"},
                headers={
                    **post_headers,
                    "Origin": "https://example.org",
                },
            )
            assert code == 403
            print("PASS: cross-origin and tokenless writes refused")

            code, created = http(
                base + "/api/task/create",
                data={"summary": "Web acceptance new", "due": "tomorrow"},
                headers=post_headers,
            )
            assert code == 200 and created["task"]["id"], created
            task_id = created["task"]["id"]

            code, edited = http(
                base + "/api/task/edit",
                data={
                    "id": task_id,
                    "summary": "Web acceptance edited",
                    "due": "August5",
                },
                headers=post_headers,
            )
            assert (
                code == 200
                and edited["task"]["summary"] == "Web acceptance edited"
            ), edited
            print("PASS: create/edit use the same Core and shared date parser")

            for action in ("start", "pause", "resume", "complete"):
                data = {"id": task_id, "action": action}
                if action == "start":
                    data["minutes"] = 1
                code, result = http(
                    base + "/api/task/action",
                    data=data,
                    headers=post_headers,
                )
                assert code == 200 and result["success"], (action, code, result)

                code, view = http(base + "/api/snapshot?live=1")
                assert code == 200, (action, view)
                if action == "start":
                    assert view["current"]["id"] == task_id, view
                    assert view["work"]["state"] == "scheduled", view
                elif action == "pause":
                    assert view["current"] is None, view
                    assert task_id in view["paused_ids"], view
                elif action == "resume":
                    assert view["current"]["id"] == task_id, view
                else:
                    assert view["current"] is None, view
                    assert all(item["id"] != task_id for item in view["tasks"]), view
                print(f"PASS: {action} through production Runtime/Core")

            todo = [
                obj.get_icalendar_component()
                for obj in tasks.todos(include_completed=True)
                if str(obj.get_icalendar_component().get("UID")) == task_id
            ]
            assert len(todo) == 1
            assert str(todo[0].get("STATUS")) == "COMPLETED", todo
            print("PASS: authoritative VTODO is completed in real CalDAV")
            return 0
        finally:
            if web is not None:
                web.terminate()
                try:
                    web.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    web.kill()
                    web.wait()
                try:
                    from caldav_assistant.internal.bootstrap import build_cli_application

                    runtime = build_cli_application().runtime
                    if runtime.status().get("status") == "running":
                        runtime.stop(timeout=5)
                except Exception:
                    pass
            if web_stream is not None:
                web_stream.close()

            radicale.terminate()
            try:
                radicale.wait(timeout=5)
            except subprocess.TimeoutExpired:
                radicale.kill()
                radicale.wait()
            radicale_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
