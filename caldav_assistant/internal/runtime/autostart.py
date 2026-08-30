"""User-level login autostart management for the background Assistant Service."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import os
import plistlib
import shlex
import subprocess
import sys


class AutostartManager:
    def __init__(
        self,
        *,
        python: str | None = None,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.python = python or sys.executable
        self._runner = runner

    @property
    def command(self) -> list[str]:
        return [self.python, "-m", "caldav_assistant.internal.runtime.observable_service"]

    @staticmethod
    def _systemd_path() -> Path:
        return Path.home() / ".config/systemd/user/caldav-assistant.service"

    @staticmethod
    def _launchd_path() -> Path:
        return Path.home() / "Library/LaunchAgents/org.caldav-assistant.service.plist"

    def _run(self, args: list[str], *, required: bool = False):
        try:
            result = self._runner(
                args,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            if required:
                raise RuntimeError(
                    f"Autostart command is unavailable: {args[0]}"
                ) from exc
            return None
        if required and getattr(result, "returncode", 1) != 0:
            raise RuntimeError(
                "Autostart command failed: " + " ".join(args)
            )
        return result

    def enable(self) -> None:
        if sys.platform.startswith("linux"):
            path = self._systemd_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            command = " ".join(shlex.quote(item) for item in self.command)
            path.write_text(
                "[Unit]\n"
                "Description=CalDAV Assistant\n\n"
                "[Service]\n"
                f"ExecStart={command}\n"
                "Restart=on-failure\n"
                "RestartSec=2\n\n"
                "[Install]\n"
                "WantedBy=default.target\n"
            )
            self._run(["systemctl", "--user", "daemon-reload"], required=True)
            self._run(
                ["systemctl", "--user", "enable", "--now", path.name],
                required=True,
            )
            return

        if sys.platform == "darwin":
            path = self._launchd_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as stream:
                plistlib.dump(
                    {
                        "Label": "org.caldav-assistant.service",
                        "ProgramArguments": self.command,
                        "RunAtLoad": True,
                        "KeepAlive": True,
                    },
                    stream,
                )
            self._run(
                ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)],
                required=True,
            )
            return

        if sys.platform.startswith("win"):
            command = subprocess.list2cmdline(self.command)
            self._run(
                [
                    "schtasks",
                    "/Create",
                    "/F",
                    "/SC",
                    "ONLOGON",
                    "/TN",
                    "CalDAV Assistant",
                    "/TR",
                    command,
                ],
                required=True,
            )
            return

        raise RuntimeError(f"Autostart is unsupported on platform: {sys.platform}")

    def disable(self, *, stop: bool = True) -> None:
        if sys.platform.startswith("linux"):
            path = self._systemd_path()
            command = ["systemctl", "--user", "disable"]
            if stop:
                command.append("--now")
            command.append(path.name)
            self._run(command)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            self._run(["systemctl", "--user", "daemon-reload"])
            return

        if sys.platform == "darwin":
            path = self._launchd_path()
            if path.exists():
                self._run(
                    ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)]
                )
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return

        if sys.platform.startswith("win"):
            if stop:
                self._run(["schtasks", "/End", "/TN", "CalDAV Assistant"])
            self._run(["schtasks", "/Delete", "/F", "/TN", "CalDAV Assistant"])
            return

        raise RuntimeError(f"Autostart is unsupported on platform: {sys.platform}")

    def is_enabled(self) -> bool:
        if sys.platform.startswith("linux"):
            path = self._systemd_path()
            if not path.is_file():
                return False
            result = self._run(
                ["systemctl", "--user", "is-enabled", "--quiet", path.name]
            )
            return result is not None and getattr(result, "returncode", 1) == 0

        if sys.platform == "darwin":
            return self._launchd_path().is_file()

        if sys.platform.startswith("win"):
            result = self._run(["schtasks", "/Query", "/TN", "CalDAV Assistant"])
            return result is not None and getattr(result, "returncode", 1) == 0

        return False

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.is_enabled(),
            "platform": sys.platform,
            "command": list(self.command),
        }


__all__ = ["AutostartManager"]
