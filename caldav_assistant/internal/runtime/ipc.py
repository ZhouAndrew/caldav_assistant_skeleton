"""Replaceable Local IPC contracts and serialization helpers."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from time import sleep
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
    def serve_forever(
        self,
        handler: Any,
        stop_event: Any,
        *,
        on_ready: Any = None,
    ) -> None: ...
    def close(self) -> None: ...

def runtime_state_dir(value: str | Path | None = None) -> Path:
    root = (
        Path(value).expanduser()
        if value is not None
        else Path.home() / ".caldav-assistant" / "runtime"
    )
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root

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
    if not all(isinstance(key, str) for key in payload):
        raise TypeError("IPC payload keys must be text")
    return dict(payload)

def sanitize_ipc_value(value: Any) -> Any:
    """Return a recursively detached, pickle-safe IPC value.

    Public domain models can be nested (``Agenda -> AgendaItem -> Task``).  A
    shallow top-level detach is therefore insufficient: Task/Event objects can
    retain their process-local ``_service`` binding several levels below the
    response root.  Rebuild dataclasses recursively and strip only process-local
    bindings.  ``raw`` advanced payloads are preserved when serializable and
    omitted only when the concrete CalDAV/library object cannot cross IPC.
    """
    if isinstance(value, Mapping):
        result = {k: sanitize_ipc_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        result = [sanitize_ipc_value(v) for v in value]
    elif isinstance(value, tuple):
        result = tuple(sanitize_ipc_value(v) for v in value)
    elif is_dataclass(value) and not isinstance(value, type):
        kwargs: dict[str, Any] = {}
        for field in fields(value):
            if not field.init:
                continue
            if field.name == "_service":
                kwargs[field.name] = None
                continue
            current = getattr(value, field.name)
            try:
                kwargs[field.name] = sanitize_ipc_value(current)
            except TypeError:
                if field.name == "raw":
                    kwargs[field.name] = None
                else:
                    raise
        try:
            result = type(value)(**kwargs)
        except Exception as exc:
            raise TypeError(
                f"IPC dataclass cannot be detached: {type(value).__name__}"
            ) from exc
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

def _read_valid_authkey(path: Path, *, retries: int = 20) -> bytes:
    """Read the winner of an auth-key creation race without accepting partial data."""
    for attempt in range(max(1, retries)):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b""
        if len(data) >= 16:
            try:
                path.chmod(0o600)
            except OSError:
                pass
            return data
        if attempt + 1 < retries:
            sleep(0.01)
    raise IPCUnavailableError("Existing IPC authentication key is invalid")

def load_or_create_authkey(state_dir: str | Path | None = None) -> bytes:
    directory = runtime_state_dir(state_dir)
    path = directory / "ipc.auth"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = b""
    if len(data) >= 16:
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return data
    if data:
        raise IPCUnavailableError("Existing IPC authentication key is invalid")

    candidate = secrets.token_bytes(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return _read_valid_authkey(path)

    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise

    try:
        path.chmod(0o600)
    except OSError:
        pass
    return candidate

__all__ = [
    "IPC_PROTOCOL_VERSION", "IPCError", "IPCUnavailableError", "IPCTimeoutError",
    "IPCRemoteError", "IPCAlreadyRunningError", "IPCClient", "IPCServer",
    "runtime_state_dir", "validate_method", "validate_payload", "sanitize_ipc_value",
    "load_or_create_authkey",
]
