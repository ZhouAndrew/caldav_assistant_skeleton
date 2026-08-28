"""Internal Runtime System.

Public extensions use :mod:`caldav_assistant.easy` / :mod:`caldav_assistant.api`.
IPC/process classes here are implementation details and are not public API.

``AssistantService`` is loaded lazily so ``python -m
caldav_assistant.internal.runtime.service`` does not pre-import the module through
this package and trigger runpy's duplicate-module warning.
"""
from typing import TYPE_CHECKING, Any

from .autostart import AutostartManager
from .client import RuntimeClient
from .ipc import (
    IPCAlreadyRunningError,
    IPCError,
    IPCRemoteError,
    IPCTimeoutError,
    IPCUnavailableError,
)
from .ipc_platform import (
    UnixSocketIPCClient,
    UnixSocketIPCServer,
    WindowsNamedPipeIPCClient,
    WindowsNamedPipeIPCServer,
)
from .scheduler import PlatformWakeScheduler
from .service_launcher import ServiceLauncher

if TYPE_CHECKING:
    from .service import AssistantService


def __getattr__(name: str) -> Any:
    if name == "AssistantService":
        from .service import AssistantService
        return AssistantService
    raise AttributeError(name)


__all__ = [
    "RuntimeClient", "AssistantService", "ServiceLauncher", "AutostartManager",
    "PlatformWakeScheduler", "IPCError", "IPCUnavailableError", "IPCTimeoutError",
    "IPCRemoteError", "IPCAlreadyRunningError", "UnixSocketIPCClient",
    "UnixSocketIPCServer", "WindowsNamedPipeIPCClient", "WindowsNamedPipeIPCServer",
]
