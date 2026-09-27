"""Loopback-only, zero-setup web front end for CalDAV Assistant.

The browser is a presentation adapter over the same RuntimeClient/Core used by the
CLI.  Task/Event truth stays in CalDAV; this module owns no second task database.
"""
from __future__ import annotations

from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from ...api.v1.errors import CalDAVAssistantError, UnavailableError, ValidationError
from ..bootstrap import build_cli_application
from ..runtime.proxies import _ensure_runtime_generation
from ..settings.keys import (
    CALDAV_EVENT_COLLECTION_URL,
    CALDAV_TASK_COLLECTION_URL,
    CALDAV_WORKLOG_COLLECTION_URL,
)


_ROLE_KEYS = {
    "task": CALDAV_TASK_COLLECTION_URL,
    "event": CALDAV_EVENT_COLLECTION_URL,
    "worklog": CALDAV_WORKLOG_COLLECTION_URL,
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


def _collection_url(value: dict[str, Any]) -> str | None:
    raw = value.get("url") or value.get("href")
    return str(raw).strip() if raw else None


def _collection_name(value: dict[str, Any]) -> str:
    raw = value.get("display_name") or value.get("name") or value.get("id") or _collection_url(value)
    return str(raw or "").strip()


def _components(value: dict[str, Any]) -> set[str]:
    raw = value.get("supported_components")
    if raw is None:
        raw = value.get("components")
    if raw is None:
        return set()
    if isinstance(raw, str):
        values: Sequence[Any] = (raw,)
    elif isinstance(raw, Sequence):
        values = raw
    else:
        values = (raw,)
    return {str(item).strip().upper() for item in values if str(item).strip()}


def _supports(value: dict[str, Any], component: str) -> bool:
    supported = _components(value)
    return not supported or component.upper() in supported


def _prefer(
    collections: list[dict[str, Any]],
    *,
    component: str,
    keywords: tuple[str, ...],
    exclude_url: str | None = None,
) -> str | None:
    supported = [
        item
        for item in collections
        if _collection_url(item)
        and _supports(item, component)
        and _collection_url(item) != exclude_url
    ]
    for item in supported:
        name = _collection_name(item).casefold()
        if any(word in name for word in keywords):
            return _collection_url(item)
    return _collection_url(supported[0]) if supported else None


def _auto_collection_roles(
    collections: list[dict[str, Any]],
    current: dict[str, str | None] | None = None,
) -> dict[str, str]:
    available = {_collection_url(item) for item in collections if _collection_url(item)}
    current = current or {}

    def keep(role: str, component: str) -> str | None:
        value = current.get(role)
        if value not in available:
            return None
        row = next((item for item in collections if _collection_url(item) == value), None)
        return value if row is not None and _supports(row, component) else None

    worklog = keep("worklog", "VEVENT") or _prefer(
        collections,
        component="VEVENT",
        keywords=("assistant work", "work log", "worklog", "work", "工作"),
    )
    task = keep("task", "VTODO") or _prefer(
        collections,
        component="VTODO",
        keywords=("task", "todo", "reminder", "待办", "任务"),
    )
    event = keep("event", "VEVENT") or _prefer(
        collections,
        component="VEVENT",
        keywords=("calendar", "event", "日历", "日程"),
        exclude_url=worklog,
    )
    if event is None:
        event = _prefer(collections, component="VEVENT", keywords=())
    if worklog is None:
        worklog = event

    missing = [
        role
        for role, value in (("task", task), ("event", event), ("worklog", worklog))
        if not value
    ]
    if missing:
        raise ValidationError(
            "服务器没有提供可用于 " + " / ".join(missing) + " 的 CalDAV collection"
        )
    return {"task": str(task), "event": str(event), "worklog": str(worklog)}


class WebActions:
    def __init__(self, app: Any):
        self.app = app

    @property
    def settings(self) -> Any:
        return self.app.ctx.settings

    def _roles(self) -> dict[str, str | None]:
        return {
            role: self.settings.get(key, None)
            for role, key in _ROLE_KEYS.items()
        }

    def setup_status(self) -> dict[str, Any]:
        status = dict(self.settings.caldav_status() or {})
        roles = self._roles()
        status["roles"] = roles
        status["ready"] = bool(
            status.get("base_url_configured")
            and roles.get("task")
            and roles.get("event")
            and roles.get("worklog")
        )
        return status

    def connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = payload.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            status = self.settings.caldav_status()
            candidates = list(status.get("discovered_candidates") or ())
            if len(candidates) == 1:
                base_url = str(candidates[0])
            else:
                raise ValidationError("请输入 CalDAV 服务器地址")

        clean_url = base_url.strip()
        if "://" not in clean_url:
            clean_url = "http://" + clean_url
        self.settings.set_caldav_base_url(clean_url)

        username = payload.get("username")
        password = payload.get("password")
        clear_credentials = bool(payload.get("clear_credentials", False))
        if username not in (None, "") or password not in (None, ""):
            if not isinstance(username, str) or not username.strip():
                raise ValidationError("请输入 CalDAV 用户名")
            if not isinstance(password, str) or not password:
                raise ValidationError("请输入 CalDAV 密码")
            self.settings.set_caldav_credentials(username.strip(), password)
        elif clear_credentials:
            self.settings.clear_caldav_credentials()

        test = self.settings.test_caldav_connection()
        collections = [dict(item) for item in (test.get("collections") or ())]
        if not collections:
            raise ValidationError("连接成功，但没有发现可用的 CalDAV collection")

        roles = _auto_collection_roles(collections, self._roles())
        for role, key in _ROLE_KEYS.items():
            self.settings.set(key, roles[role])

        # First-run setup starts from an intentionally empty local cache.  Prime one
        # verified Task/Event snapshot immediately so the normal startup fallback is
        # usable even when a server rejects an optimized pending-only REPORT.  This
        # is the same SyncEngine used by the background service, not a Web cache.
        refresh = getattr(self.settings, "_experimental_cache_refresh", None)
        if callable(refresh):
            refresh()

        result = self.setup_status()
        result.update(
            {
                "connection_ok": True,
                "collection_count": len(collections),
                "collections": collections,
                "roles": roles,
                "ready": True,
            }
        )
        return result

    def snapshot(self, *, live: bool = False) -> dict[str, Any]:
        _ensure_runtime_generation(self.app.runtime)
        route = "agenda.startup_snapshot" if live else "agenda.cached_startup_snapshot"
        try:
            bundle = self.app.runtime.call(route, days=7, kind="task")
        except (UnavailableError, RuntimeError):
            if live:
                raise
            bundle = self.app.runtime.call("agenda.startup_snapshot", days=7, kind="task")
        if not isinstance(bundle, dict):
            raise RuntimeError("后台返回的日程格式无效")

        agenda = bundle.get("agenda")
        current = bundle.get("current_task")
        verified = bool(bundle.get("current_work_verified", True))
        paused_ids = (
            list(self.app.ctx.session.paused_task_ids() or ())
            if verified
            else []
        )
        work = (
            self.app.runtime.call("work_period.status", task_id=current.id)
            if current is not None and verified
            else None
        )
        return {
            "current": _item(current),
            "current_work_verified": verified,
            "recommended": _item(bundle.get("recommendation")),
            "upcoming": [_item(row) for row in getattr(agenda, "items", ())],
            "tasks": [_item(row) for row in bundle.get("tasks") or ()],
            "paused_ids": paused_ids,
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
            try:
                work = self.app.runtime.call(
                    "work_period.allocate",
                    task_id=task_id,
                    seconds=minutes * 60,
                )
            except Exception as exc:
                return {
                    "success": True,
                    "warning": f"任务已开始，但工作时长未设置：{exc}",
                }
        return {
            "success": True,
            "message": result.message or "操作完成",
            "work": work,
        }

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
            raise ValidationError("任务标题不能为空且不能超过 500 字")
        fields: dict[str, Any] = {}
        if payload.get("due"):
            fields["due"] = _date(payload["due"], self.app.ctx.time)
        result = self.app.ctx.tasks.create(summary.strip(), **fields)
        if not result.success:
            raise RuntimeError(result.message or "任务创建失败")
        return {"success": True, "task": _item(result.affected)}

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
        if not result.success:
            raise RuntimeError(result.message or "任务修改失败")
        return {"success": True, "task": _item(result.affected)}


def make_handler(actions: WebActions, *, token: str, port: int | None = None):
    assets = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/style.css": ("style.css", "text/css; charset=utf-8"),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            self._send(
                status,
                json.dumps(value, ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )

        def _trusted(self) -> bool:
            actual_port = int(getattr(self.server, "server_port", port or 0))
            allowed_hosts = {
                f"127.0.0.1:{actual_port}",
                f"localhost:{actual_port}",
            }
            host = self.headers.get("Host")
            if host not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return not origin or origin in {f"http://{item}" for item in allowed_hosts}

        def do_GET(self) -> None:
            if not self._trusted():
                self._json(403, {"error": "请求来源不允许"})
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/api/health":
                self._json(200, {"service": "caldav-assistant-web", "version": 1})
                return
            if path == "/api/setup/status":
                try:
                    self._json(200, actions.setup_status())
                except Exception as exc:
                    self._json(503, {"error": f"暂时无法读取设置：{exc}"})
                return
            if path == "/api/snapshot":
                try:
                    self._json(200, actions.snapshot(live=parsed.query == "live=1"))
                except Exception as exc:
                    self._json(503, {"error": f"暂时无法读取日程：{exc}"})
                return
            if path == "/api/token":
                self._json(200, {"token": token})
                return
            if path in assets:
                name, media_type = assets[path]
                self._send(
                    200,
                    files("caldav_assistant.internal.web")
                    .joinpath("static", name)
                    .read_bytes(),
                    media_type,
                )
                return
            self._json(404, {"error": "页面不存在"})

        def do_POST(self) -> None:
            if not self._trusted() or self.headers.get("X-Assistant-Token") != token:
                self._json(403, {"error": "请求来源不允许"})
                return
            if (
                self.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
                != "application/json"
            ):
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
                if path == "/api/setup/connect":
                    result = actions.connect(payload)
                elif path == "/api/task/action":
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


def _is_existing_server(port: int) -> bool:
    if port <= 0:
        return False
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.35) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read())
        return data.get("service") == "caldav-assistant-web"
    except Exception:
        return False


def _open_browser(address: str) -> None:
    try:
        import webbrowser

        webbrowser.open(address)
    except Exception:
        # The URL is always printed, so headless/minimal desktops still have a
        # complete path without turning browser-launch failure into app failure.
        pass


def serve(
    app: Any = None,
    *,
    port: int = 8765,
    open_browser: bool = True,
) -> int:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")

    if port and _is_existing_server(port):
        address = f"http://127.0.0.1:{port}/"
        print(f"CalDAV Assistant 网页版已在运行：{address}", flush=True)
        if open_browser:
            _open_browser(address)
        return 0

    application = app if app is not None else build_cli_application()
    token = secrets.token_urlsafe(32)
    actions = WebActions(application)

    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", port),
            make_handler(actions, token=token, port=port),
        )
    except OSError:
        if not port:
            raise
        # Another program owns the preferred port. Do not make the user diagnose
        # ports: choose a free loopback port and continue.
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(actions, token=token),
        )

    with server:
        actual_port = int(server.server_port)
        address = f"http://127.0.0.1:{actual_port}/"
        print(f"CalDAV Assistant 网页版：{address}", flush=True)
        if actual_port != port and port:
            print(f"端口 {port} 已被占用，已自动改用 {actual_port}。", flush=True)
        if open_browser:
            _open_browser(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="打开 CalDAV Assistant 本机网页版；首次连接也在网页内完成",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="本机端口；占用时自动换端口，0 表示直接选择空闲端口",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="只启动服务，不自动打开默认浏览器",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return serve(port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
