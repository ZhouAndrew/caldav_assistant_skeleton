"""WordPress REST transport authenticated with Application Passwords.

The stable WordPressService owns Outbox/retry semantics.  This adapter owns only
HTTP transport and translation to the WordPress REST API, so callers keep using
the same create_log/create_post/update_post/test_connection contract as WP-CLI.
"""
from __future__ import annotations

import base64
from datetime import datetime
from html import escape
import json
import mimetypes
from pathlib import Path
import ssl
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...api.v1.errors import UnavailableError, ValidationError
from .transports import WPCLIAdapter


class ApplicationPasswordRESTAdapter:
    """WordPress adapter using REST + a WordPress Application Password."""

    def __init__(
        self,
        base_url: str | None,
        username: str | None,
        application_password: str | None,
        *,
        opener: Callable[..., Any] | None = None,
        timeout: float = 20.0,
        clock: Callable[[], datetime] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.username = str(username or "").strip()
        # WordPress displays Application Passwords in grouped form with spaces.
        # Authentication accepts the compact value; normalizing makes pasted/file
        # values deterministic while never exposing the secret.
        self.application_password = "".join(str(application_password or "").split())
        self._opener = opener or urlopen
        self._timeout = float(timeout)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._ssl_context = ssl_context

    def _ensure_config(self) -> None:
        if not self.base_url:
            raise UnavailableError("WordPress REST base URL is not configured")
        if not (
            self.base_url.startswith("http://")
            or self.base_url.startswith("https://")
        ):
            raise ValidationError("WordPress REST base URL must use http:// or https://")
        if not self.username:
            raise UnavailableError("WordPress REST username is not configured")
        if not self.application_password:
            raise UnavailableError("WordPress Application Password is not configured")

    def _api_url(self, path: str) -> str:
        self._ensure_config()
        clean = "/" + str(path or "").lstrip("/")
        return self.base_url + "/wp-json/wp/v2" + clean

    def _authorization(self) -> str:
        raw = f"{self.username}:{self.application_password}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _decode(raw: bytes) -> Any:
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _error_detail(raw: bytes, fallback: str) -> str:
        value = ApplicationPasswordRESTAdapter._decode(raw)
        if isinstance(value, dict):
            message = value.get("message")
            code = value.get("code")
            if message and code:
                return f"{code}: {message}"
            if message:
                return str(message)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
        return fallback

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        json_body: Any = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if json_body is not None and body is not None:
            raise ValueError("Use json_body or body, not both")
        request_headers = {
            "Authorization": self._authorization(),
            "Accept": "application/json",
            "User-Agent": "CalDAV-Assistant/1.0 WordPress-REST",
        }
        request_headers.update(headers or {})
        data = body
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
        request = Request(
            self._api_url(path),
            data=data,
            headers=request_headers,
            method=method,
        )
        kwargs: dict[str, Any] = {"timeout": self._timeout}
        if self._ssl_context is not None:
            kwargs["context"] = self._ssl_context
        try:
            response = self._opener(request, **kwargs)
            with response:
                raw = response.read()
        except HTTPError as exc:
            try:
                raw = exc.read()
            except Exception:
                raw = b""
            detail = self._error_detail(raw, str(exc.reason or exc))
            raise UnavailableError(
                f"WordPress REST HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise UnavailableError(f"WordPress REST request failed: {exc}") from exc
        return self._decode(raw)

    def _local_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("WordPress clock must return datetime")
        return value.astimezone() if value.tzinfo is None else value

    @staticmethod
    def _raw_title(post: Any) -> str:
        if not isinstance(post, dict):
            return ""
        value = post.get("title")
        if isinstance(value, dict):
            return str(value.get("raw") or value.get("rendered") or "").strip()
        return str(value or "").strip()

    @staticmethod
    def _raw_content(post: Any) -> str:
        if not isinstance(post, dict):
            return ""
        value = post.get("content")
        if isinstance(value, dict):
            return str(value.get("raw") or value.get("rendered") or "")
        return str(value or "")

    def _list_post_records(
        self,
        value: datetime,
        *,
        post_type: str = "post",
    ) -> list[dict[str, Any]]:
        if post_type != "post":
            raise ValidationError(
                "Application Password REST transport currently supports post_type=post"
            )
        query = urlencode(
            {
                "context": "edit",
                "per_page": 100,
                "search": WPCLIAdapter._daily_title(value).split()[0][:3],
            }
        )
        items = self._request(f"/posts?{query}")
        if not isinstance(items, list):
            raise UnavailableError("WordPress REST returned invalid post-list data")
        return [item for item in items if isinstance(item, dict)]

    def _find_daily_post_record(
        self,
        value: datetime,
        *,
        post_type: str = "post",
    ) -> dict[str, Any] | None:
        for item in self._list_post_records(value, post_type=post_type):
            title = self._raw_title(item)
            if not WPCLIAdapter._daily_title_matches(title, value):
                continue
            post_id = item.get("id")
            if post_id not in (None, ""):
                return {"id": post_id, "title": title, "post": item}
        return None

    def _post(self, post_id: Any) -> dict[str, Any]:
        value = self._request(f"/posts/{post_id}?context=edit")
        if not isinstance(value, dict):
            raise UnavailableError("WordPress REST returned invalid post data")
        return value

    def _post_content(self, post_id: Any) -> str:
        return self._raw_content(self._post(post_id))

    @staticmethod
    def _rest_fields(fields: dict[str, Any]) -> dict[str, Any]:
        result = dict(fields)
        aliases = {
            "post_status": "status",
            "post_title": "title",
            "post_content": "content",
            "post_excerpt": "excerpt",
            "post_author": "author",
        }
        for old, new in aliases.items():
            if old in result and new not in result:
                result[new] = result.pop(old)
        result.pop("post_type", None)
        return result

    def create_post(self, title: str, content: str = "", **fields: Any) -> dict[str, Any]:
        if not str(title).strip():
            raise ValidationError("WordPress post title must not be empty")
        post_type = str(fields.get("post_type", "post") or "post")
        if post_type != "post":
            raise ValidationError(
                "Application Password REST transport currently supports post_type=post"
            )
        payload = self._rest_fields(fields)
        payload["title"] = str(title)
        payload["content"] = str(content)
        result = self._request("/posts", method="POST", json_body=payload)
        if not isinstance(result, dict) or result.get("id") is None:
            raise UnavailableError("WordPress REST returned no post id")
        return {
            "id": result["id"],
            "url": str(result.get("link") or ""),
        }

    def update_post(self, post_id: Any, **changes: Any) -> dict[str, Any]:
        if isinstance(post_id, bool) or post_id in (None, ""):
            raise ValidationError("WordPress post id must not be empty")
        payload = self._rest_fields(changes)
        result = self._request(
            f"/posts/{post_id}",
            method="POST",
            json_body=payload,
        )
        if not isinstance(result, dict) or result.get("id") is None:
            raise UnavailableError("WordPress REST returned no updated post id")
        return {"id": result["id"]}

    def create_log(self, text: str, **metadata: Any) -> dict[str, Any]:
        logged_at = metadata.pop("_logged_at", None)
        if logged_at:
            try:
                now = datetime.fromisoformat(str(logged_at))
            except ValueError as exc:
                raise ValidationError("Invalid WordPress log timestamp") from exc
            if now.tzinfo is None:
                now = now.astimezone()
        else:
            now = self._local_now()

        entry_title = metadata.pop("title", None)
        request_id = metadata.pop("_request_id", None)
        show_clock = bool(metadata.pop("_show_clock", True))
        post_status = metadata.pop("post_status", metadata.pop("status", "draft"))
        post_type = str(metadata.pop("post_type", "post") or "post")

        entry = WPCLIAdapter._render_log_entry(
            text,
            at=now,
            entry_title=str(entry_title).strip() if entry_title else None,
            request_id=request_id,
            show_clock=show_clock,
        )
        marker = WPCLIAdapter._log_marker(request_id)
        item = self._find_daily_post_record(now, post_type=post_type)

        if item is None:
            return self.create_post(
                WPCLIAdapter._daily_title(now),
                entry,
                post_status=post_status,
                post_type=post_type,
                **metadata,
            )

        post_id = item["id"]
        existing = self._post_content(post_id)
        if marker and marker in existing:
            return {"id": post_id}

        self.update_post(
            post_id,
            post_content=WPCLIAdapter._append_content(existing, entry),
        )
        return {"id": post_id}

    def read_daily_log(
        self,
        *,
        at: datetime | None = None,
        post_type: str = "post",
    ) -> dict[str, Any] | None:
        value = self._local_now() if at is None else at
        if not isinstance(value, datetime):
            raise TypeError("WordPress daily-log timestamp must be datetime")
        if value.tzinfo is None:
            value = value.astimezone()
        item = self._find_daily_post_record(value, post_type=post_type)
        if item is None:
            return None
        post_id = item["id"]
        post = self._post(post_id)
        return {
            "id": post_id,
            "title": item["title"],
            "content": self._raw_content(post),
        }

    def ensure_daily_log_reference(
        self,
        *,
        at: datetime | None = None,
        post_type: str = "post",
    ) -> dict[str, Any]:
        value = self._local_now() if at is None else at
        if not isinstance(value, datetime):
            raise TypeError("WordPress daily-log timestamp must be datetime")
        if value.tzinfo is None:
            value = value.astimezone()
        item = self._find_daily_post_record(value, post_type=post_type)
        if item is None:
            created = self.create_post(
                WPCLIAdapter._daily_title(value),
                "",
                post_status="publish",
                post_type=post_type,
            )
            post_id = created["id"]
            title = WPCLIAdapter._daily_title(value)
            url = created.get("url") or ""
        else:
            post_id = item["id"]
            title = item["title"]
            post = self._post(post_id)
            url = str(post.get("link") or "")
        return {"id": post_id, "title": title, "url": url}

    def attach_file(self, file_path: str | Path, **metadata: Any) -> dict[str, Any]:
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise ValidationError(f"Attachment file not found: {path}")

        logged_at = metadata.pop("_logged_at", None)
        if logged_at:
            try:
                at = datetime.fromisoformat(str(logged_at))
            except ValueError as exc:
                raise ValidationError("Invalid WordPress attachment timestamp") from exc
            if at.tzinfo is None:
                at = at.astimezone()
        else:
            at = self._local_now()

        reference = self.ensure_daily_log_reference(
            at=at,
            post_type=str(metadata.pop("post_type", "post") or "post"),
        )
        post_id = reference["id"]
        mime_type = str(
            metadata.pop("mime_type", "")
            or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )
        uploaded = self._request(
            "/media",
            method="POST",
            body=path.read_bytes(),
            headers={
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "Content-Type": mime_type,
            },
        )
        if not isinstance(uploaded, dict) or uploaded.get("id") is None:
            raise UnavailableError("WordPress REST returned no media id")
        attachment_id = uploaded["id"]
        attached = self._request(
            f"/media/{attachment_id}",
            method="POST",
            json_body={"post": post_id},
        )
        if not isinstance(attached, dict):
            raise UnavailableError("WordPress REST media parent update failed")
        file_url = str(
            attached.get("source_url")
            or uploaded.get("source_url")
            or ""
        )

        safe_name = escape(path.name, quote=False)
        safe_url = escape(file_url, quote=True)
        if mime_type.startswith("image/"):
            block = (
                f'<!-- wp:image {{"id":{attachment_id},"sizeSlug":"large"}} -->\n'
                f'<figure class="wp-block-image size-large"><img src="{safe_url}" '
                f'alt="{safe_name}" class="wp-image-{attachment_id}"/></figure>\n'
                '<!-- /wp:image -->'
            )
        elif mime_type.startswith("video/"):
            block = (
                f'<!-- wp:video {{"id":{attachment_id}}} -->\n'
                f'<figure class="wp-block-video"><video controls src="{safe_url}"></video></figure>\n'
                '<!-- /wp:video -->'
            )
        elif mime_type.startswith("audio/"):
            block = (
                f'<!-- wp:audio {{"id":{attachment_id}}} -->\n'
                f'<figure class="wp-block-audio"><audio controls src="{safe_url}"></audio></figure>\n'
                '<!-- /wp:audio -->'
            )
        else:
            block = (
                f'<!-- wp:file {{"id":{attachment_id},"href":"{safe_url}"}} -->\n'
                f'<div class="wp-block-file"><a href="{safe_url}">{safe_name}</a></div>\n'
                '<!-- /wp:file -->'
            )

        existing = self._post_content(post_id)
        self.update_post(
            post_id,
            post_content=WPCLIAdapter._append_content(existing, block),
        )
        return {
            "id": attachment_id,
            "post_id": post_id,
            "url": file_url,
            "post_url": reference["url"],
            "filename": path.name,
            "mime_type": mime_type,
        }

    def test_connection(self) -> bool:
        try:
            value = self._request("/users/me?context=edit")
        except Exception:
            return False
        return isinstance(value, dict) and value.get("id") is not None


__all__ = ["ApplicationPasswordRESTAdapter"]
