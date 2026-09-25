from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from uuid import uuid4

import pytest

from caldav_assistant.internal.clients.terminal import StdConsoleIO
from caldav_assistant.internal.presentation import TextRenderer
from caldav_assistant.internal.prompts import Menu
from caldav_assistant.internal.runtime.ipc_platform import UnixSocketIPCClient, UnixSocketIPCServer


@pytest.mark.parametrize("width", [20, 39, 40, 49, 50, 60, 80, 120, 200])
def test_menu_renderer_survives_extreme_terminal_widths(width):
    io = StdConsoleIO(
        input_fn=lambda _prompt: "0",
        stdout=StringIO(),
        terminal_width_fn=lambda: width,
    )
    menu = Menu(io, page_size=1000)
    view = menu.presentation(
        "Extreme menu",
        [f"Choice {index:04d}" for index in range(1, 1001)],
        page_size=1000,
    )
    rendered = TextRenderer(max_width=width).render(view)

    assert "1. Choice 0001" in rendered
    assert "1000. Choice 1000" in rendered
    assert rendered.endswith("0. Back")
    # Width-aware packing may use multiple columns, but it must never lose choices.
    for index in (1, 2, 9, 10, 99, 100, 999, 1000):
        assert f"{index}. Choice {index:04d}" in rendered


def test_menu_renderer_handles_wide_cjk_labels_without_corrupting_order():
    io = StdConsoleIO(
        input_fn=lambda _prompt: "0",
        stdout=StringIO(),
        terminal_width_fn=lambda: 120,
    )
    menu = Menu(io, page_size=200)
    labels = [f"任务 {index:03d} — 学习与复习" for index in range(1, 201)]
    view = menu.presentation("中文压力菜单", labels, page_size=200)
    rendered = TextRenderer(max_width=120).render(view)

    assert "1. 任务 001 — 学习与复习" in rendered
    assert "200. 任务 200 — 学习与复习" in rendered
    assert rendered.index("1. 任务 001") < rendered.index("200. 任务 200")


@pytest.mark.skipif(__import__("os").name == "nt", reason="AF_UNIX concurrency stress")
def test_real_unix_ipc_accepts_many_simultaneous_authenticated_clients(tmp_path):
    endpoint = "extreme-" + uuid4().hex
    stop = __import__("threading").Event()
    server = UnixSocketIPCServer(endpoint, state_dir=tmp_path)
    calls = 0
    lock = __import__("threading").Lock()

    def handler(method, payload):
        nonlocal calls
        if method != "runtime.ping":
            raise AssertionError(method)
        with lock:
            calls += 1
        return {"status": "ok", "value": payload["value"]}

    thread = __import__("threading").Thread(
        target=server.serve_forever,
        args=(handler, stop),
        daemon=True,
    )
    thread.start()

    client = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=2.0)
    deadline = __import__("time").monotonic() + 3.0
    while True:
        try:
            assert client.call("runtime.ping", {"value": -1})["status"] == "ok"
            break
        except Exception:
            if __import__("time").monotonic() >= deadline:
                raise
            __import__("time").sleep(0.01)

    workers = 32
    rounds = 10
    barrier = Barrier(workers)

    def hammer(worker):
        local = UnixSocketIPCClient(endpoint, state_dir=tmp_path, timeout=2.0)
        barrier.wait()
        values = []
        for round_number in range(rounds):
            value = worker * 1000 + round_number
            result = local.call("runtime.ping", {"value": value})
            assert result == {"status": "ok", "value": value}
            values.append(value)
        return values

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            batches = list(pool.map(hammer, range(workers)))
        assert sum(len(batch) for batch in batches) == workers * rounds
        assert calls >= workers * rounds
    finally:
        stop.set()
        server.close()
        thread.join(3.0)

    assert not thread.is_alive()
