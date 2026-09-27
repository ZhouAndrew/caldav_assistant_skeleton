"""Loopback-only HTTP presentation backed by the existing RuntimeClient/Core.

The browser never receives an IPC method name or a Python object.  This module
exposes only explicit UI operations and does not store a second task state.
"""
from __future__ import annotations

from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
from typing import Any
from urllib.parse import urlsplit

from ...api.v1.errors import CalDAVAssistantError, UnavailableError, ValidationError
from ..bootstrap import build_cli_application
from ..runtime.proxies import _ensure_runtime_generation


def _item(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    obj = getattr(value, "value", value)
    if obj is None:
        return None
    kind = getattr(value, "kind", None) or obj.__class__.__name__.lower()
    return {
        "id": str(getattr(obj, "id", "") or ""),
        "kind": str(kind),
        "summary": str(getattr(obj, "summary", "") or ""),
        "when": _iso(getattr(value, "when", None)),
        "start": _iso(getattr(obj, "start", None)),
        "due": _iso(getattr(obj, "due", None)),
        "end": _iso(getattr(obj, "end", None)),
        "status": str(getattr(obj, "status", "") or ""),
        "completed": bool(getattr(obj, "completed", False)),
        "stale": bool(getattr(obj, "stale", False)),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, (date, datetime)) else None


def _date(value: Any, temporal: Any) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise ValidationError("日期必须是文本，且不超过 80 个字符")
    # A date-only field must never acquire an implicit midnight time.
    return temporal.parse_date(value, bias="future")


class WebActions:
    def __init__(self, app: Any):
        self.app = app

    def snapshot(self, *, live: bool = False) -> dict[str, Any]:
        _ensure_runtime_generation(self.app.runtime)
        route = "agenda.live_startup_snapshot" if live else "agenda.startup_snapshot"
        try:
            bundle = self.app.runtime.call(route, days=7, kind="task")
        except UnavailableError:
            if live:
                raise
            # A first installation may have no verified snapshot yet. Read live
            # once rather than showing an empty task list or a misleading error.
            bundle = self.app.runtime.call("agenda.live_startup_snapshot", days=7, kind="task")
        if not isinstance(bundle, dict):
            raise RuntimeError("后台返回的日程格式无效")
        agenda = bundle.get("agenda")
        current = bundle.get("current_task")
        work = (
            self.app.runtime.call("work_period.status", task_id=current.id)
            if current is not None and bundle.get("current_work_verified", True)
            else None
        )
        return {
            "current": _item(current),
            "current_work_verified": bool(bundle.get("current_work_verified", True)),
            "recommended": _item(bundle.get("recommendation")),
            "upcoming": [_item(row) for row in getattr(agenda, "items", ())],
            "tasks": [_item(row) for row in bundle.get("tasks") or ()],
            "paused_ids": list(bundle.get("paused_task_ids") or ()),
            "work": work,
            "snapshot": bool(bundle.get("stale", False)),
        }

    def action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        task_id = payload.get("id")
        if action not in {"start", "pause", "resume", "complete"}:
            raise ValidationError("不支持的操作")
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 512:
            raise ValidationError("请选择任务")
        minutes = payload.get("minutes")
        if minutes not in (None, ""):
            if action not in {"start", "resume"} or type(minutes) is not int or not 1 <= minutes <= 1440:
                raise ValidationError("工作时长应为 1 至 1440 分钟")
        result = getattr(self.app.ctx.tasks, action)(task_id)
        if not result.success:
            raise RuntimeError(result.message or "任务操作失败")
        work = None
        if minutes not in (None, ""):
            # The Task has already started. If scheduling the reminder fails, say so
            # explicitly; never claim the whole compound operation was rolled back.
            try:
                work = self.app.runtime.call("work_period.allocate", task_id=task_id, seconds=minutes * 60)
            except Exception as exc:
                return {"success": True, "warning": f"任务已开始，但工作时长未设置：{exc}"}
        return {"success": True, "message": result.message or "操作完成", "work": work}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
            raise ValidationError("任务标题不能为空且不能超过 500 字")
        fields: dict[str, Any] = {}
        if payload.get("due"):
            fields["due"] = _date(payload["due"], self.app.ctx.time)
        result = self.app.ctx.tasks.create(summary.strip(), **fields)
        return {"success": bool(result.success), "task": _item(result.affected)}

    def edit(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = payload.get("id")
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 512:
            raise ValidationError("请选择任务")
        changes: dict[str, Any] = {}
        if "summary" in payload:
            title = payload["summary"]
            if not isinstance(title, str) or not title.strip() or len(title) > 500:
                raise ValidationError("任务标题不能为空且不能超过 500 字")
            changes["summary"] = title.strip()
        if "due" in payload:
            changes["due"] = _date(payload["due"], self.app.ctx.time)
        if not changes:
            raise ValidationError("没有需要修改的字段")
        result = self.app.ctx.tasks.update(task_id, **changes)
        return {"success": bool(result.success), "task": _item(result.affected)}


def make_handler(actions: WebActions, *, port: int, token: str):
    assets = {"/": ("index.html", "text/html; charset=utf-8"),
              "/app.js": ("app.js", "text/javascript; charset=utf-8"),
              "/style.css": ("style.css", "text/css; charset=utf-8")}
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _trusted(self) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return not origin or origin in {f"http://{host}" for host in allowed_hosts}

        def do_GET(self) -> None:
            if not self._trusted():
                self._json(403, {"error": "请求来源不允许"})
                return
            path = urlsplit(self.path).path
            if path == "/api/snapshot":
                try:
                    self._json(200, actions.snapshot(live=urlsplit(self.path).query == "live=1"))
                except Exception as exc:
                    self._json(503, {"error": f"暂时无法读取日程：{exc}"})
                return
            if path == "/api/token":
                self._json(200, {"token": token})
                return
            if path in assets:
                name, media_type = assets[path]
                self._send(200, files("caldav_assistant.internal.web").joinpath("static", name).read_bytes(), media_type)
                return
            self._json(404, {"error": "页面不存在"})

        def do_POST(self) -> None:
            if not self._trusted() or self.headers.get("X-Assistant-Token") != token:
                self._json(403, {"error": "请求来源不允许"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._json(415, {"error": "请求必须使用 JSON"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValidationError("请求内容过长或为空")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValidationError("请求格式无效")
                path = urlsplit(self.path).path
                if path == "/api/task/action":
                    result = actions.action(payload)
                elif path == "/api/task/create":
                    result = actions.create(payload)
                elif path == "/api/task/edit":
                    result = actions.edit(payload)
                else:
                    self._json(404, {"error": "操作不存在"})
                    return
                self._json(200, result)
            except (CalDAVAssistantError, ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(503, {"error": f"后台操作失败：{exc}"})

    return Handler


def serve(app: Any = None, *, port: int = 8765, open_browser: bool = False) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    application = app if app is not None else build_cli_application()
    token = secrets.token_urlsafe(32)
    with ThreadingHTTPServer(("127.0.0.1", port), make_handler(WebActions(application), port=port, token=token)) as server:
        address = f"http://127.0.0.1:{port}/"
        print(f"CalDAV Assistant 网页版：{address}", flush=True)
        if open_browser:
            import webbrowser
            webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="在本机打开 CalDAV Assistant 网页入口")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动时打开默认浏览器")
    args = parser.parse_args()
    serve(port=args.port, open_browser=args.open)


if __name__ == "__main__":
    main()
