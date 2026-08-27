"""Platform Local IPC adapters based on authenticated multiprocessing connections."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from multiprocessing.connection import Client, Listener, wait
from pathlib import Path
from threading import RLock, Thread
from typing import Any
from uuid import uuid4
import os
import re

from .ipc import (
    IPC_PROTOCOL_VERSION, IPCAlreadyRunningError, IPCRemoteError, IPCTimeoutError,
    IPCUnavailableError, load_or_create_authkey, runtime_state_dir, sanitize_ipc_value,
    validate_method, validate_payload,
)

_ENDPOINT_RE = re.compile(r"[^A-Za-z0-9_.-]+")

def _clean_endpoint(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("IPC endpoint must be non-empty text")
    clean = _ENDPOINT_RE.sub("-", value.strip()).strip("-")
    if not clean:
        raise ValueError("IPC endpoint contains no usable characters")
    return clean

class _ConnectionIPCClient:
    family = ""
    def __init__(self, endpoint: str, *, state_dir: str | Path | None = None, timeout: float = 10.0) -> None:
        self.endpoint = _clean_endpoint(endpoint)
        self.state_dir = runtime_state_dir(state_dir)
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")

    @property
    def address(self):
        raise NotImplementedError

    def call(self, method: str, payload: Mapping[str, Any] | None = None) -> Any:
        request_id = uuid4().hex
        request = {
            "version": IPC_PROTOCOL_VERSION,
            "id": request_id,
            "method": validate_method(method),
            "payload": sanitize_ipc_value(validate_payload(payload)),
        }
        try:
            connection = Client(self.address, family=self.family, authkey=load_or_create_authkey(self.state_dir))
        except (OSError, EOFError) as exc:
            raise IPCUnavailableError(f"Local IPC is unavailable: {self.address}") from exc
        try:
            connection.send(request)
            ready = wait([connection], timeout=self.timeout)
            if not ready:
                raise IPCTimeoutError(f"IPC request timed out: {method}")
            response = connection.recv()
        except (EOFError, OSError) as exc:
            raise IPCUnavailableError("Local IPC connection was lost") from exc
        finally:
            try: connection.close()
            except OSError: pass
        if not isinstance(response, dict) or response.get("version") != IPC_PROTOCOL_VERSION:
            raise IPCUnavailableError("Invalid IPC response")
        if response.get("id") != request_id:
            raise IPCUnavailableError("IPC response id mismatch")
        if response.get("ok") is True:
            return response.get("result")
        error = response.get("error") or {}
        raise IPCRemoteError(error.get("type", "RemoteError"), error.get("message", "remote error"), module=error.get("module"))

    request = call

class _ConnectionIPCServer:
    family = ""
    def __init__(self, endpoint: str, *, state_dir: str | Path | None = None) -> None:
        self.endpoint = _clean_endpoint(endpoint)
        self.state_dir = runtime_state_dir(state_dir)
        self._listener = None
        self._close_lock = RLock()

    @property
    def address(self):
        raise NotImplementedError

    def _prepare(self) -> None:
        return None

    def _cleanup(self) -> None:
        return None

    def _serve_connection(self, connection: Any, handler: Callable[[str, dict[str, Any]], Any]) -> None:
        request_id = None
        try:
            request = connection.recv()
            if not isinstance(request, dict) or request.get("version") != IPC_PROTOCOL_VERSION:
                raise ValueError("unsupported IPC protocol")
            request_id = request.get("id")
            method = validate_method(request.get("method"))
            payload = validate_payload(request.get("payload"))
            result = handler(method, payload)
            response = {"version": IPC_PROTOCOL_VERSION, "id": request_id, "ok": True, "result": sanitize_ipc_value(result)}
        except Exception as exc:
            response = {
                "version": IPC_PROTOCOL_VERSION, "id": request_id, "ok": False,
                "error": {"type": type(exc).__name__, "module": type(exc).__module__, "message": str(exc)},
            }
        try:
            connection.send(response)
        except (BrokenPipeError, EOFError, OSError):
            pass
        finally:
            try: connection.close()
            except OSError: pass

    def serve_forever(self, handler: Callable[[str, dict[str, Any]], Any], stop_event: Any) -> None:
        if not callable(handler):
            raise TypeError("IPC handler must be callable")
        self._prepare()
        authkey = load_or_create_authkey(self.state_dir)
        try:
            try:
                listener = Listener(self.address, family=self.family, authkey=authkey)
            except OSError as exc:
                raise IPCUnavailableError(f"Cannot bind local IPC endpoint: {self.address}") from exc
            with self._close_lock:
                self._listener = listener
            while not stop_event.is_set():
                try:
                    connection = listener.accept()
                except (OSError, EOFError):
                    if stop_event.is_set(): break
                    raise
                Thread(target=self._serve_connection, args=(connection, handler), name="caldav-assistant-ipc-request", daemon=True).start()
        finally:
            self.close(); self._cleanup()

    def close(self) -> None:
        with self._close_lock:
            listener, self._listener = self._listener, None
        if listener is not None:
            try: listener.close()
            except OSError: pass

class UnixSocketIPCClient(_ConnectionIPCClient):
    family = "AF_UNIX"
    @property
    def address(self) -> str:
        return str(self.state_dir / f"{self.endpoint}.sock")

class UnixSocketIPCServer(_ConnectionIPCServer):
    family = "AF_UNIX"
    @property
    def address(self) -> str:
        return str(self.state_dir / f"{self.endpoint}.sock")
    def _endpoint_is_live(self) -> bool:
        if not Path(self.address).exists(): return False
        try:
            result = UnixSocketIPCClient(self.endpoint, state_dir=self.state_dir, timeout=0.5).call("runtime.ping")
        except Exception:
            return False
        return isinstance(result, dict) and result.get("status") == "ok"
    def _prepare(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = Path(self.address)
        if not path.exists(): return
        if self._endpoint_is_live():
            raise IPCAlreadyRunningError(f"Local IPC endpoint already active: {path}")
        try: path.unlink()
        except FileNotFoundError: pass
        except OSError as exc: raise IPCUnavailableError(f"Cannot remove stale IPC socket: {path}") from exc
    def _cleanup(self) -> None:
        try: Path(self.address).unlink()
        except FileNotFoundError: pass
        except OSError: pass

class WindowsNamedPipeIPCClient(_ConnectionIPCClient):
    family = "AF_PIPE"
    @property
    def address(self) -> str:
        return rf"\\.\pipe\{self.endpoint}"

class WindowsNamedPipeIPCServer(_ConnectionIPCServer):
    family = "AF_PIPE"
    @property
    def address(self) -> str:
        return rf"\\.\pipe\{self.endpoint}"

__all__ = ["UnixSocketIPCClient", "UnixSocketIPCServer", "WindowsNamedPipeIPCClient", "WindowsNamedPipeIPCServer"]
