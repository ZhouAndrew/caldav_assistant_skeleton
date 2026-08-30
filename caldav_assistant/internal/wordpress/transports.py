"""Concrete WordPress transport implemented with WP-CLI.

The application service owns reliability/outbox semantics.  This adapter owns only
process execution and translation between the stable WordPress service calls and
WP-CLI arguments.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from typing import Any
import shutil
import subprocess

from ...api.v1.errors import UnavailableError, ValidationError


class WPCLIAdapter:
    """Production WordPress adapter using the local ``wp`` executable."""

    def __init__(
        self,
        wordpress_path: str | Path | None = None,
        *,
        executable: str | None = None,
        runner: Callable[..., Any] | None = None,
        timeout: float = 20.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.wordpress_path = (
            None if wordpress_path in (None, "") else str(Path(wordpress_path).expanduser())
        )
        self._executable = executable
        self._runner = runner or subprocess.run
        self._timeout = float(timeout)
        self._clock = clock or (lambda: datetime.now().astimezone())

    def _find_executable(self) -> str:
        if self._executable:
            return self._executable
        executable = shutil.which("wp")
        if executable:
            return executable
        raise UnavailableError("WP-CLI executable 'wp' is unavailable")

    def _base_command(self) -> list[str]:
        command = [self._find_executable()]
        if self.wordpress_path:
            command.append(f"--path={self.wordpress_path}")
        return command

    @staticmethod
    def _argument(name: str, value: Any) -> str:
        if isinstance(value, bool):
            value = "1" if value else "0"
        elif isinstance(value, (list, tuple, set)):
            value = ",".join(str(item) for item in value)
        elif value is None:
            value = ""
        return f"--{name}={value}"

    def _run(self, args: list[str]) -> str:
        command = self._base_command() + args
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UnavailableError(f"WP-CLI failed: {exc}") from exc

        returncode = int(getattr(result, "returncode", 0) or 0)
        stdout = str(getattr(result, "stdout", "") or "").strip()
        stderr = str(getattr(result, "stderr", "") or "").strip()
        if returncode != 0:
            detail = stderr or stdout or f"exit status {returncode}"
            raise UnavailableError(f"WP-CLI failed: {detail}")
        return stdout

    @staticmethod
    def _created_id(stdout: str) -> int | str:
        value = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        if not value:
            raise UnavailableError("WP-CLI returned no post id")
        try:
            return int(value)
        except ValueError:
            return value

    def _local_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("WordPress clock must return datetime")
        return value.astimezone() if value.tzinfo is None else value

    @staticmethod
    def _daily_title(value: datetime) -> str:
        months = (
            "",
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        )
        weekdays = (
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        )
        return f"{months[value.month]} {value.day} {weekdays[value.weekday()]} {value.year}"

    @staticmethod
    def _daily_title_matches(title: str, value: datetime) -> bool:
        """Match the user's existing shell-script convention without whitespace assumptions."""
        months = (
            ("", ""),
            ("January", "Jan"), ("February", "Feb"), ("March", "Mar"),
            ("April", "Apr"), ("May", "May"), ("June", "Jun"),
            ("July", "Jul"), ("August", "Aug"), ("September", "Sep"),
            ("October", "Oct"), ("November", "Nov"), ("December", "Dec"),
        )
        weekdays = (
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        )
        text = str(title or "")
        folded = text.casefold()
        full_month, short_month = months[value.month]
        has_month = full_month.casefold() in folded or short_month.casefold() in folded
        has_day = re.search(rf"(?<!\d){value.day}(?!\d)", text) is not None
        has_year = str(value.year) in text
        has_weekday = weekdays[value.weekday()].casefold() in folded
        return has_month and has_day and has_year and has_weekday

    @staticmethod
    def _log_marker(request_id: Any) -> str:
        clean = str(request_id or "").strip()
        return f"<!-- caldav-assistant-log:{clean} -->" if clean else ""

    @classmethod
    def _render_log_entry(
        cls,
        text: str,
        *,
        at: datetime,
        entry_title: str | None = None,
        request_id: Any = None,
    ) -> str:
        safe_text = escape(str(text), quote=False).replace("\n", "<br>")
        clock_text = at.strftime("%H:%M")
        if entry_title:
            visible = f"{clock_text} <strong>{escape(str(entry_title), quote=False)}</strong>"
            if safe_text:
                visible += f"<br>{safe_text}"
        else:
            visible = f"{clock_text} {safe_text}".rstrip()

        marker = cls._log_marker(request_id)
        block = f"<!-- wp:paragraph -->\n<p>{visible}</p>\n<!-- /wp:paragraph -->"
        return f"{marker}\n{block}" if marker else block

    @staticmethod
    def _decode_post_list(stdout: str) -> list[dict[str, Any]]:
        try:
            items = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            raise UnavailableError("WP-CLI returned invalid post-list JSON") from exc
        if not isinstance(items, list):
            raise UnavailableError("WP-CLI returned invalid post-list data")
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _item_post_id(item: dict[str, Any]) -> int | str | None:
        value = item.get("ID")
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)

    def _list_post_titles(self, *, post_type: str = "post", search: str | None = None) -> list[dict[str, Any]]:
        args = [
            "post",
            "list",
            self._argument("post_type", post_type),
            self._argument("post_status", "any"),
        ]
        if search:
            args.append(self._argument("search", search))
        args.extend(["--fields=ID,post_title", "--format=json"])
        return self._decode_post_list(self._run(args))

    def _find_post_by_title(self, title: str, *, post_type: str = "post") -> int | str | None:
        for item in self._list_post_titles(post_type=post_type, search=title):
            if str(item.get("post_title") or "").strip() != title:
                continue
            post_id = self._item_post_id(item)
            if post_id is not None:
                return post_id
        return None

    def _find_daily_post(self, value: datetime, *, post_type: str = "post") -> int | str | None:
        # Match the user's long-standing find-today-post.sh behavior: month may be
        # full or abbreviated and extra spaces are irrelevant.  Listing title/ID
        # pairs also lets Assistant reuse daily posts created by that script.
        for item in self._list_post_titles(post_type=post_type):
            title = str(item.get("post_title") or "")
            if not self._daily_title_matches(title, value):
                continue
            post_id = self._item_post_id(item)
            if post_id is not None:
                return post_id
        return None

    def _post_content(self, post_id: Any) -> str:
        return self._run(["post", "get", str(post_id), "--field=post_content"])

    @staticmethod
    def _append_content(existing: str, entry: str) -> str:
        left = str(existing or "").rstrip()
        return f"{left}\n\n{entry}" if left else entry

    def create_log(self, text: str, **metadata: Any) -> dict[str, Any]:
        """Append one log entry to today's single WordPress daily-log post.

        The stable public operation remains ``create_log``.  Transport semantics are
        daily aggregation: an existing user/Assistant daily post is updated when
        present, otherwise one post for the day is created.  A hidden request marker
        makes Outbox retries idempotent without adding visible noise to the post.
        """
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
        daily_title = self._daily_title(now)
        entry_title = metadata.pop("title", None)
        request_id = metadata.pop("_request_id", None)
        post_status = metadata.pop("post_status", metadata.pop("status", "draft"))
        post_type = str(metadata.pop("post_type", "post") or "post")

        entry = self._render_log_entry(
            text,
            at=now,
            entry_title=str(entry_title).strip() if entry_title else None,
            request_id=request_id,
        )
        marker = self._log_marker(request_id)
        post_id = self._find_daily_post(now, post_type=post_type)

        if post_id is None:
            return self.create_post(
                daily_title,
                entry,
                post_status=post_status,
                post_type=post_type,
                **metadata,
            )

        existing = self._post_content(post_id)
        if marker and marker in existing:
            # At-least-once Outbox retry after a remote success must not duplicate
            # the same visible diary line.
            return {"id": post_id}

        self.update_post(
            post_id,
            post_content=self._append_content(existing, entry),
        )
        return {"id": post_id}

    def read_daily_log(
        self,
        *,
        at: datetime | None = None,
        post_type: str = "post",
    ) -> dict[str, Any] | None:
        """Return the actual WordPress daily-log post and content for one local day."""
        value = self._local_now() if at is None else at
        if not isinstance(value, datetime):
            raise TypeError("WordPress daily-log timestamp must be datetime")
        if value.tzinfo is None:
            value = value.astimezone()
        post_id = self._find_daily_post(value, post_type=post_type)
        if post_id is None:
            return None
        return {
            "id": post_id,
            "title": self._daily_title(value),
            "content": self._post_content(post_id),
        }

    def create_post(self, title: str, content: str = "", **fields: Any) -> dict[str, Any]:
        if not str(title).strip():
            raise ValidationError("WordPress post title must not be empty")
        args = [
            "post",
            "create",
            self._argument("post_title", title),
            self._argument("post_content", content),
        ]
        for key, value in fields.items():
            args.append(self._argument(str(key), value))
        args.append("--porcelain")
        post_id = self._created_id(self._run(args))
        return {"id": post_id}

    def update_post(self, post_id: Any, **changes: Any) -> dict[str, Any]:
        if isinstance(post_id, bool) or post_id in (None, ""):
            raise ValidationError("WordPress post id must not be empty")
        args = ["post", "update", str(post_id)]
        for key, value in changes.items():
            args.append(self._argument(str(key), value))
        self._run(args)
        return {"id": post_id}

    def test_connection(self) -> bool:
        try:
            self._run(["core", "is-installed"])
        except Exception:
            return False
        return True


__all__ = ["WPCLIAdapter"]