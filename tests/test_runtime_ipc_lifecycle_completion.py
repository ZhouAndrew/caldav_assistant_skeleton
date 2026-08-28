from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4
import os

import pytest

from caldav_assistant.internal.runtime.ipc import IPCAlreadyRunningError
from caldav_assistant.internal.runtime.ipc_platform import UnixSocketIPCClient, UnixSocketIPCServer


pytestmark = pytest.mark.skipif(os.name == "nt", reason="AF_UNIX lifecycle tests")


def _start(server, stop):
    thread = Thread(
        target=server.serve_forever,
        args=(lambda method, payload: {"status": "ok"} if method == "runtime.ping" else payload, stop),
        daemon=True,
    )
    thread.start()
    return thread


def _wait_ready(client, timeout=1.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        try:
            if client.call("runtime.ping")["status"] == "ok": return
        except Exception:
            sleep(0.01)
    raise AssertionError("AF_UNIX server did not become ready")


def test_stale_socket_is_reclaimed_and_cleaned_on_stop(tmp_path):
    endpoint = "pytest-" + uuid4().hex
    stop = Event(); server = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    path = Path(server.address)
    path.write_text("stale")
    assert len(os.fsencode(server.address)) <= 100
    thread = _start(server, stop)
    client = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=0.2)
    _wait_ready(client)
    assert path.exists()
    stop.set(); server.close(); thread.join(1.0)
    assert not thread.is_alive()
    assert not path.exists()


def test_second_server_refuses_live_singleton_endpoint(tmp_path):
    endpoint = "pytest-" + uuid4().hex
    stop = Event(); first = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    thread = _start(first, stop)
    client = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=0.2)
    _wait_ready(client)

    second = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    with pytest.raises(IPCAlreadyRunningError):
        second.serve_forever(lambda method, payload: None, Event())

    stop.set(); first.close(); thread.join(1.0)


def test_singleton_lock_blocks_second_server_before_socket_bind(tmp_path):
    endpoint = "pytest-" + uuid4().hex
    first = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    second = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    first._prepare()
    try:
        with pytest.raises(IPCAlreadyRunningError):
            second._prepare()
    finally:
        first._cleanup()


def test_bad_authentication_does_not_kill_running_server(tmp_path):
    from multiprocessing import AuthenticationError
    from multiprocessing.connection import Client

    endpoint = "pytest-" + uuid4().hex
    stop = Event()
    server = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    thread = _start(server, stop)
    client = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=0.2)
    _wait_ready(client)

    with pytest.raises(AuthenticationError):
        Client(server.address, family="AF_UNIX", authkey=b"wrong-auth-key")

    assert client.call("runtime.ping")["status"] == "ok"
    stop.set()
    server.close()
    thread.join(1.0)
    assert not thread.is_alive()

@pytest.mark.skipif(os.name == "nt", reason="raw AF_UNIX handshake regression")
def test_client_disconnect_during_auth_handshake_does_not_kill_server(tmp_path):
    import socket

    endpoint = "pytest-" + uuid4().hex
    stop = Event()
    server = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    thread = _start(server, stop)
    client = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=0.2)
    _wait_ready(client)

    # Connect as a raw Unix socket and disappear before multiprocessing's auth
    # challenge can complete.  Listener.accept() can surface BrokenPipeError here.
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    raw.connect(server.address)
    raw.close()

    deadline = monotonic() + 1.0
    while monotonic() < deadline:
        try:
            assert client.call("runtime.ping")["status"] == "ok"
            break
        except Exception:
            sleep(0.01)
    else:
        raise AssertionError("server died after an aborted auth handshake")

    stop.set()
    server.close()
    thread.join(1.0)
    assert not thread.is_alive()


def test_nested_agenda_domain_models_are_recursively_detached_for_ipc(tmp_path):
    from caldav_assistant.api import Agenda, AgendaItem, Task

    endpoint = "pytest-" + uuid4().hex
    stop = Event()
    server = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    task = Task(id="task-1", summary="Report", raw=lambda: None)
    task._service = lambda: None
    agenda = Agenda([AgendaItem(value=task, when=None, kind="task")])

    def handler(method, payload):
        if method == "runtime.ping":
            return {"status": "ok"}
        return agenda

    thread = Thread(
        target=server.serve_forever,
        args=(handler, stop),
        daemon=True,
    )
    thread.start()
    client = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=0.5)
    _wait_ready(client)

    received = client.call("agenda.today")
    assert isinstance(received, Agenda)
    assert received.items[0].value.id == "task-1"
    assert received.items[0].value._service is None
    # A process-local raw library object must not make the whole Agenda response
    # unserializable; advanced raw data is transported only when pickle-safe.
    assert received.items[0].value.raw is None

    stop.set()
    server.close()
    thread.join(1.0)
    assert not thread.is_alive()
