"""On-demand background service launcher used by RuntimeClient."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import os
import subprocess
import sys

from .ipc import runtime_state_dir


class ServiceLauncher:
    def __init__(
        self,
        *,
        python: str | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        state_dir: str | Path | None = None,
    ) -> None:
        self.python = python or sys.executable
        self._popen = popen
        self.state_dir = runtime_state_dir(state_dir)

    @property
    def log_path(self) -> Path:
        return self.state_dir / "service.log"

    def _open_log(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(self.log_path, flags, 0o600)
        try:
            os.chmod(self.log_path, 0o600)
        except OSError:
            pass
        return os.fdopen(fd, "ab", buffering=0)

    def start(self) -> Any:
        command = [
            self.python,
            "-m",
            "caldav_assistant.internal.runtime.versioned_observable_service",
        ]
        log = self._open_log()
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            # The background service must never keep arbitrary foreground CLI
            # handles alive. This matters especially on Windows when the CLI is
            # launched from PowerShell, CI, an editor, or any caller capturing
            # stdout/stderr with a pipe: inheriting that pipe's write handle keeps
            # the caller waiting for EOF after the foreground command has exited.
            # Python 3.10+ supports close_fds=True on Windows with redirected
            # standard handles, which is exactly our supported runtime range.
            "close_fds": True,
            "cwd": str(Path.home()),
        }
        if os.name == "nt":
            flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
            kwargs["creationflags"] = flags
        else:
            kwargs["start_new_session"] = True
        try:
            return self._popen(command, **kwargs)
        finally:
            log.close()


__all__ = ["ServiceLauncher"]
