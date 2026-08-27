"""Internal Runtime System.

Public extensions use :mod:`caldav_assistant.easy` / :mod:`caldav_assistant.api`.
IPC/process classes here are implementation details and are not public API.
"""
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
from .service import AssistantService
from .service_launcher import ServiceLauncher

__all__ = [
    "RuntimeClient", "AssistantService", "ServiceLauncher", "AutostartManager",
    "PlatformWakeScheduler", "IPCError", "IPCUnavailableError", "IPCTimeoutError",
    "IPCRemoteError", "IPCAlreadyRunningError", "UnixSocketIPCClient",
    "UnixSocketIPCServer", "WindowsNamedPipeIPCClient", "WindowsNamedPipeIPCServer",
]
