"""Concrete operating-system notification adapters.

MODULE CONTRACT
- Imports/calls: stdlib process discovery/execution + stable public errors.
- Provides: LinuxNotificationAdapter, MacOSNotificationAdapter,
  WindowsNotificationAdapter.
- Must not: contain Reminder/Task/Event rules, read Assistant storage/settings,
  or decide *when* a notification is due.

No shell is used.  Title/body are passed as process arguments where practical, so
notification text is not interpreted as shell code.

Interactive notification actions intentionally fail explicitly for now.  The frozen
v1 specification exposes ``actions=None`` but does not define the action descriptor or
activation/callback protocol.  Silently dropping actions would be incorrect; inventing
a platform-specific public shape here would freeze the wrong API.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
import shutil
import subprocess

from ...api.v1.errors import UnavailableError


def _reject_unfrozen_actions(actions: Any) -> None:
    if actions:
        raise UnavailableError(
            "Interactive notification actions are not implemented yet"
        )


class _CommandNotificationAdapter:
    """Shared, injectable subprocess mechanics for platform adapters."""

    executable_names: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        runner: Callable[..., Any] | None = None,
        which: Callable[[str], str | None] | None = None,
        timeout: float = 10.0,
        sound_enabled: bool | Callable[[], bool] = True,
    ) -> None:
        self._runner = runner or subprocess.run
        self._which = which or shutil.which
        self._timeout = timeout
        self._sound_enabled = sound_enabled

    def _notification_sound_enabled(self) -> bool:
        configured_value = (
            self._sound_enabled()
            if callable(self._sound_enabled)
            else self._sound_enabled
        )
        return bool(configured_value)

    def _find_executable(self) -> str:
        for executable_name in self.executable_names:
            executable_path = self._which(executable_name)
            if executable_path:
                return executable_path
        executable_choices = ", ".join(self.executable_names)
        raise UnavailableError(
            f"System notification command is unavailable: {executable_choices}"
        )

    def _run(self, command: list[str]) -> None:
        try:
            completed_process = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UnavailableError(
                f"System notification failed: {exc}"
            ) from exc

        exit_code = int(getattr(completed_process, "returncode", 0) or 0)
        if exit_code != 0:
            standard_error = str(
                getattr(completed_process, "stderr", "") or ""
            ).strip()
            failure_detail = standard_error or f"exit status {exit_code}"
            raise UnavailableError(
                f"System notification failed: {failure_detail}"
            )


class LinuxNotificationAdapter(_CommandNotificationAdapter):
    """Linux desktop notifications through the standard ``notify-send`` tool."""

    executable_names = ("notify-send",)

    def notify(
        self,
        title: str,
        body: str = "",
        actions: Any = None,
    ) -> None:
        _reject_unfrozen_actions(actions)
        notify_send_path = self._find_executable()
        sound_hint = (
            "--hint=string:sound-name:alarm-clock-elapsed"
            if self._notification_sound_enabled()
            else "--hint=boolean:suppress-sound:true"
        )
        self._run(
            [
                notify_send_path,
                "--app-name=CalDAV Assistant",
                sound_hint,
                title,
                body,
            ]
        )


class MacOSNotificationAdapter(_CommandNotificationAdapter):
    """macOS Notification Center through the built-in ``osascript`` command."""

    executable_names = ("osascript",)

    _SCRIPT_WITH_SOUND = """on run argv
set notificationTitle to item 1 of argv
set notificationBody to item 2 of argv
display notification notificationBody with title notificationTitle sound name "Glass"
end run"""

    _SCRIPT_SILENT = """on run argv
set notificationTitle to item 1 of argv
set notificationBody to item 2 of argv
display notification notificationBody with title notificationTitle
end run"""

    def notify(
        self,
        title: str,
        body: str = "",
        actions: Any = None,
    ) -> None:
        _reject_unfrozen_actions(actions)
        osascript_path = self._find_executable()
        notification_script = (
            self._SCRIPT_WITH_SOUND
            if self._notification_sound_enabled()
            else self._SCRIPT_SILENT
        )
        self._run(
            [
                osascript_path,
                "-e",
                notification_script,
                "--",
                title,
                body,
            ]
        )


class WindowsNotificationAdapter(_CommandNotificationAdapter):
    """Windows 10/11 toast notification through built-in PowerShell + WinRT."""

    executable_names = ("powershell.exe", "powershell", "pwsh.exe", "pwsh")

    _SCRIPT_WITH_SOUND = r"""
param([string]$Title, [string]$Body)

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$escapedTitle = [System.Security.SecurityElement]::Escape($Title)
$escapedBody = [System.Security.SecurityElement]::Escape($Body)

$xmlText = "<toast><visual><binding template='ToastGeneric'><text>$escapedTitle</text><text>$escapedBody</text></binding></visual><audio src='ms-winsoundevent:Notification.Reminder' loop='false'/></toast>"
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($xmlText)

$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("CalDAV Assistant")
$notifier.Show($toast)
""".strip()

    _SCRIPT_SILENT = r"""
param([string]$Title, [string]$Body)

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$escapedTitle = [System.Security.SecurityElement]::Escape($Title)
$escapedBody = [System.Security.SecurityElement]::Escape($Body)

$xmlText = "<toast><visual><binding template='ToastGeneric'><text>$escapedTitle</text><text>$escapedBody</text></binding></visual><audio silent='true'/></toast>"
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($xmlText)

$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("CalDAV Assistant")
$notifier.Show($toast)
""".strip()

    def notify(
        self,
        title: str,
        body: str = "",
        actions: Any = None,
    ) -> None:
        _reject_unfrozen_actions(actions)
        powershell_path = self._find_executable()
        notification_script = (
            self._SCRIPT_WITH_SOUND
            if self._notification_sound_enabled()
            else self._SCRIPT_SILENT
        )
        self._run(
            [
                powershell_path,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                notification_script,
                title,
                body,
            ]
        )
