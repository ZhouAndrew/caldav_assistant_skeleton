"""Platform Local IPC adapters based on authenticated multiprocessing connections."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
from queue import Empty, Queue
from threading import RLock, Thread
from typing import Any
from uuid import uuid4
import hashlib
import os
import re
import tempfile

from .ipc import (
    IPC_PROTOCOL_VERSION,
    IPCAlreadyRunningError,
    IPCRemoteError,
    IPCTimeoutError,
    IPCUnavailableError,
    load_or_create_authkey,
    runtime_state_dir,
    sanitize_ipc_value,
    validate_method,
    validate_payload,
)

_ENDPOINT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_UNIX_SOCKET_SAFE_BYTES = 100


def _unix_socket_address(state_dir: Path, endpoint: str) -> str:
    """Return a deterministic AF_UNIX path that fits conservative sun_path limits.

    Linux commonly allows 107 pathname bytes and several BSD/macOS variants allow
    fewer.  Keep a conservative 100-byte ceiling.  Normal installations retain the
    human-readable socket in ``state_dir``; only long paths fall back to a private,
    per-user, per-state-directory runtime location.
    """
    filename = f"{endpoint}.sock"
    direct = state_dir / filename
    if len(os.fsencode(str(direct))) <= _UNIX_SOCKET_SAFE_BYTES:
        return str(direct)

    state_scope = hashlib.sha256(os.fsencode(str(state_dir.absolute()))).hexdigest()[:16]
    endpoint_scope = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:16]
    uid = str(getattr(os, "getuid", lambda: 0)())
    roots: list[Path] = []
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        roots.append(Path(xdg_runtime))
    roots.append(Path(tempfile.gettempdir()))

    for root in roots:
        directory = root / f"caldav-assistant-{uid}-{state_scope}"
        candidate = directory / f"ipc-{endpoint_scope}.sock"
        if len(os.fsencode(str(candidate))) > _UNIX_SOCKET_SAFE_BYTES:
            continue
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        return str(candidate)

    raise IPCUnavailableError(
        "Cannot construct an AF_UNIX socket path within the platform path limit"
    )


def _clean_endpoint(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("IPC endpoint must be non-empty text")
    clean = _ENDPOINT_RE.sub("-", value.strip()).strip("-")
    if not clean:
        raise ValueError("IPC endpoint contains no usable characters")
    return clean


class _ConnectionIPCClient:
    family = ""

    def __init__(
        self,
        endpoint: str,
        *,
        state_dir: str | Path | None = None,
        timeout: float = 10.0,
    ) -> None:
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
            connection = Client(
                self.address,
                family=self.family,
                authkey=load_or_create_authkey(self.state_dir),
            )
        except (AuthenticationError, OSError, EOFError) as exc:
            raise IPCUnavailableError(
                f"Local IPC is unavailable: {self.address}"
            ) from exc

        try:
            connection.send(request)
            if not connection.poll(self.timeout):
                raise IPCTimeoutError(f"IPC request timed out: {method}")
            response = connection.recv()
        except (EOFError, OSError) as exc:
            raise IPCUnavailableError("Local IPC connection was lost") from exc
        finally:
            try:
                connection.close()
            except OSError:
                pass

        if not isinstance(response, dict) or response.get("version") != IPC_PROTOCOL_VERSION:
            raise IPCUnavailableError("Invalid IPC response")
        if response.get("id") != request_id:
            raise IPCUnavailableError("IPC response id mismatch")
        if response.get("ok") is True:
            return response.get("result")
        error = response.get("error") or {}
        raise IPCRemoteError(
            error.get("type", "RemoteError"),
            error.get("message", "remote error"),
            module=error.get("module"),
        )

    request = call


class _ConnectionIPCServer:
    family = ""

    def __init__(self, endpoint: str, *, state_dir: str | Path | None = None) -> None:
        self.endpoint = _clean_endpoint(endpoint)
        self.state_dir = runtime_state_dir(state_dir)
        self._listener = None
        self._close_lock = RLock()
        self._bound = False

    @property
    def address(self):
        raise NotImplementedError

    def _prepare(self) -> None:
        return None

    def _cleanup(self) -> None:
        return None

    def _serve_connection(
        self,
        connection: Any,
        handler: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        request_id = None
        try:
            request = connection.recv()
            if not isinstance(request, dict) or request.get("version") != IPC_PROTOCOL_VERSION:
                raise ValueError("unsupported IPC protocol")
            request_id = request.get("id")
            method = validate_method(request.get("method"))
            payload = validate_payload(request.get("payload"))
            result = handler(method, payload)
            response = {
                "version": IPC_PROTOCOL_VERSION,
                "id": request_id,
                "ok": True,
                "result": sanitize_ipc_value(result),
            }
        except Exception as exc:
            response = {
                "version": IPC_PROTOCOL_VERSION,
                "id": request_id,
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "module": type(exc).__module__,
                    "message": str(exc),
                },
            }
        try:
            connection.send(response)
        except (BrokenPipeError, EOFError, OSError):
            pass
        finally:
            try:
                connection.close()
            except OSError:
                pass

    @staticmethod
    def _accept_interruptibly(listener: Any, stop_event: Any) -> Any | None:
        """Run blocking Listener.accept() behind a daemon worker.

        ``multiprocessing.connection.Listener.accept`` is not guaranteed to be
        interrupted when another thread closes the listener.  Polling a queue keeps
        the service thread responsive to ``stop_event`` on Unix sockets and Windows
        named pipes alike.  Any platform accept worker left blocked during process
        shutdown is daemon-only and therefore cannot keep the service process alive.
        """
        result: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def accept_one() -> None:
            try:
                result.put((True, listener.accept()))
            except BaseException as exc:
                result.put((False, exc))

        Thread(
            target=accept_one,
            name="caldav-assistant-ipc-accept",
            daemon=True,
        ).start()

        while not stop_event.is_set():
            try:
                ok, value = result.get(timeout=0.10)
            except Empty:
                continue
            if ok:
                return value
            raise value
        return None

    def serve_forever(
        self,
        handler: Callable[[str, dict[str, Any]], Any],
        stop_event: Any,
        *,
        on_ready: Callable[[], Any] | None = None,
    ) -> None:
        if not callable(handler):
            raise TypeError("IPC handler must be callable")

        prepared = False
        try:
            self._prepare()
            prepared = True
            authkey = load_or_create_authkey(self.state_dir)
            try:
                listener = Listener(
                    self.address,
                    family=self.family,
                    authkey=authkey,
                )
            except OSError as exc:
                raise IPCUnavailableError(
                    f"Cannot bind local IPC endpoint: {self.address}"
                ) from exc

            with self._close_lock:
                self._listener = listener
                self._bound = True

            if not stop_event.is_set() and callable(on_ready):
                on_ready()

            while not stop_event.is_set():
                try:
                    connection = self._accept_interruptibly(listener, stop_event)
                except AuthenticationError:
                    # A process without the local auth key must not be able to kill
                    # the whole background service merely by connecting.
                    if stop_event.is_set():
                        break
                    continue
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, EOFError):
                    # ``Listener.accept()`` performs the authentication handshake
                    # before returning a connection.  A client can disappear during
                    # that handshake (for example when a bounded CLI probe exits).
                    # That is a single-connection failure, not a server failure.
                    if stop_event.is_set():
                        break
                    continue
                except OSError:
                    if stop_event.is_set():
                        break
                    raise
                if connection is None:
                    break
                Thread(
                    target=self._serve_connection,
                    args=(connection, handler),
                    name="caldav-assistant-ipc-request",
                    daemon=True,
                ).start()
        finally:
            self.close()
            if prepared:
                self._cleanup()

    def close(self) -> None:
        with self._close_lock:
            listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass


class UnixSocketIPCClient(_ConnectionIPCClient):
    family = "AF_UNIX"

    @property
    def address(self) -> str:
        return _unix_socket_address(self.state_dir, self.endpoint)


class UnixSocketIPCServer(_ConnectionIPCServer):
    family = "AF_UNIX"

    def __init__(
        self,
        endpoint: str,
        *,
        state_dir: str | Path | None = None,
    ) -> None:
        super().__init__(endpoint, state_dir=state_dir)
        self._singleton_file = None

    @property
    def address(self) -> str:
        return _unix_socket_address(self.state_dir, self.endpoint)

    @property
    def _lock_path(self) -> Path:
        return self.state_dir / f"{self.endpoint}.lock"

    def _acquire_singleton(self) -> None:
        # ``flock`` is released automatically by the kernel if the process dies,
        # so an unclean shutdown cannot permanently strand the singleton lock.
        import fcntl

        stream = self._lock_path.open("a+b")
        try:
            os.chmod(self._lock_path, 0o600)
        except OSError:
            pass
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise IPCAlreadyRunningError(
                f"Local IPC endpoint is starting or already active: {self.address}"
            ) from exc
        self._singleton_file = stream

    def _release_singleton(self) -> None:
        stream, self._singleton_file = self._singleton_file, None
        if stream is None:
            return
        try:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            stream.close()

    def _endpoint_is_live(self) -> bool:
        if not Path(self.address).exists():
            return False
        try:
            result = UnixSocketIPCClient(
                self.endpoint,
                state_dir=self.state_dir,
                timeout=0.5,
            ).call("runtime.ping")
        except Exception:
            return False
        return isinstance(result, dict) and result.get("status") == "ok"

    def _prepare(self) -> None:
        self._bound = False
        self._acquire_singleton()
        path = Path(self.address)
        if not path.exists():
            return
        if self._endpoint_is_live():
            self._release_singleton()
            raise IPCAlreadyRunningError(
                f"Local IPC endpoint already active: {path}"
            )
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._release_singleton()
            raise IPCUnavailableError(
                f"Cannot remove stale IPC socket: {path}"
            ) from exc

    def _cleanup(self) -> None:
        try:
            if self._bound:
                try:
                    Path(self.address).unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
        finally:
            self._bound = False
            self._release_singleton()


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


__all__ = [
    "UnixSocketIPCClient",
    "UnixSocketIPCServer",
    "WindowsNamedPipeIPCClient",
    "WindowsNamedPipeIPCServer",
]
