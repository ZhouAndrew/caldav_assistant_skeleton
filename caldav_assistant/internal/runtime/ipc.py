"""Replaceable Local IPC contracts and serialization helpers."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
import os
import pickle
import secrets

IPC_PROTOCOL_VERSION = 1

class IPCError(RuntimeError):
    pass

class IPCUnavailableError(IPCError):
    pass

class IPCTimeoutError(IPCError):
    pass

class IPCAlreadyRunningError(IPCError):
    pass

class IPCRemoteError(IPCError):
    def __init__(self, error_type: str, message: str, *, module: str | None = None) -> None:
        self.error_type = str(error_type)
        self.message = str(message)
        self.module = module
        super().__init__(f"{self.error_type}: {self.message}")

class IPCClient(Protocol):
    def call(self, method: str, payload: Mapping[str, Any] | None = None) -> Any: ...

class IPCServer(Protocol):
    def serve_forever(self, handler: Any, stop_event: Any) -> None: ...
    def close(self) -> None: ...

def runtime_state_dir(value: str | Path | None = None) -> Path:
    return Path(value).expanduser() if value is not None else Path.home() / ".caldav-assistant" / "runtime"

def validate_method(method: Any) -> str:
    if not isinstance(method, str) or not method.strip():
        raise ValueError("IPC method must be non-empty text")
    clean = method.strip()
    if any(ch.isspace() for ch in clean):
        raise ValueError("IPC method must not contain whitespace")
    return clean

def validate_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise TypeError("IPC payload must be a mapping")
    return dict(payload)

def sanitize_ipc_value(value: Any) -> Any:
    """Return a pickle-safe detached value without leaking service bindings."""
    if isinstance(value, Mapping):
        result = {k: sanitize_ipc_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        result = [sanitize_ipc_value(v) for v in value]
    elif isinstance(value, tuple):
        result = tuple(sanitize_ipc_value(v) for v in value)
    else:
        result = value
        if hasattr(value, "_service"):
            try:
                import copy
                result = copy.copy(value)
                setattr(result, "_service", None)
            except Exception:
                result = value
    try:
        pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        raise TypeError(f"IPC value is not serializable: {type(value).__name__}") from exc
    return result

def load_or_create_authkey(state_dir: str | Path | None = None) -> bytes:
    directory = runtime_state_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ipc.auth"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = secrets.token_bytes(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    if not data:
        raise IPCUnavailableError("IPC authentication key is empty")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data

__all__ = [
    "IPC_PROTOCOL_VERSION", "IPCError", "IPCUnavailableError", "IPCTimeoutError",
    "IPCRemoteError", "IPCAlreadyRunningError", "IPCClient", "IPCServer",
    "runtime_state_dir", "validate_method", "validate_payload", "sanitize_ipc_value",
    "load_or_create_authkey",
]
