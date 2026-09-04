"""Small cross-platform process-exit helpers for Runtime lifecycle commands.

No third-party process manager is needed.  The helper is intentionally internal and
is used only after a service has acknowledged shutdown, so it never becomes a second
source of Runtime truth.
"""
from __future__ import annotations

from time import monotonic, sleep
from typing import Callable
import os


def process_is_alive(pid: int) -> bool:
    """Return whether *pid* still represents a live process without terminating it."""
    try:
        clean_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if clean_pid <= 0:
        return False

    if os.name == "nt":
        # Do not use os.kill(pid, 0) on Windows: unlike POSIX it is implemented
        # through TerminateProcess for ordinary signals.  A waitable process handle
        # is both safe and cheap for the short shutdown window used here.
        import ctypes

        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        ERROR_INVALID_PARAMETER = 87

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        handle = kernel32.OpenProcess(SYNCHRONIZE, False, clean_pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == ERROR_INVALID_PARAMETER:
                return False
            # Access denied or another transient OpenProcess failure means we cannot
            # prove the process is gone. Treat it as alive and let the bounded wait
            # fail visibly rather than claiming a clean shutdown too early.
            return True
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(clean_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def wait_for_process_exit(
    pid: int,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.05,
    alive: Callable[[int], bool] = process_is_alive,
) -> bool:
    """Wait a bounded time for a known service process to finish teardown."""
    limit = float(timeout)
    interval = float(poll_interval)
    if limit <= 0 or interval <= 0:
        raise ValueError("process exit wait values must be positive")

    deadline = monotonic() + limit
    while alive(pid):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(interval, remaining))
    return True


__all__ = ["process_is_alive", "wait_for_process_exit"]
