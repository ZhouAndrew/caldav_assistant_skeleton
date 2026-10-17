"""On-demand background service launcher used by RuntimeClient."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import os
import subprocess
import sys

from .ipc import runtime_state_dir


PRODUCTION_SERVICE_MODULE = "caldav_assistant.internal.runtime.versioned_observable_service"


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
        self._last_log_path: Path | None = None

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def log_path(self) -> Path:
        """Return the most recently allocated launch log.

        Before the first launch, retain the historical service.log location as a
        compatibility fallback for internal callers that only inspect the path.
        New launches never write that shared file.
        """
        return self._last_log_path or (self.state_dir / "service.log")

    def _open_log(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.log_dir.chmod(0o700)
        except OSError:
            pass

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        stem = f"service-{stamp}-p{os.getpid()}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)

        for collision in range(1000):
            suffix = "" if collision == 0 else f"-{collision}"
            path = self.log_dir / f"{stem}{suffix}.log"
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                continue

            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            self._last_log_path = path
            return os.fdopen(fd, "wb", buffering=0)

        raise RuntimeError("Unable to allocate a unique background-service log file")

    def start(self) -> Any:
        command = [self.python, "-m", PRODUCTION_SERVICE_MODULE]
        log = self._open_log()
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
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


__all__ = ["PRODUCTION_SERVICE_MODULE", "ServiceLauncher"]
