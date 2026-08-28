"""Concrete WordPress transport implemented with WP-CLI.

The application service owns reliability/outbox semantics.  This adapter owns only
process execution and translation between the stable WordPress service calls and
WP-CLI arguments.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
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
    ) -> None:
        self.wordpress_path = (
            None if wordpress_path in (None, "") else str(Path(wordpress_path).expanduser())
        )
        self._executable = executable
        self._runner = runner or subprocess.run
        self._timeout = float(timeout)

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

    def create_log(self, text: str, **metadata: Any) -> dict[str, Any]:
        title = str(metadata.pop("title", "CalDAV Assistant Log"))
        post_status = metadata.pop("post_status", metadata.pop("status", "draft"))
        post_type = metadata.pop("post_type", "post")
        return self.create_post(
            title,
            text,
            post_status=post_status,
            post_type=post_type,
            **metadata,
        )

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
