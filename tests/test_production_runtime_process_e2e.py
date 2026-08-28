from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import os
import shutil
import subprocess
import sys

import pytest

from caldav_assistant.internal.runtime.client import RuntimeClient
from caldav_assistant.internal.runtime.ipc_platform import UnixSocketIPCClient


pytestmark = pytest.mark.skipif(os.name == "nt", reason="AF_UNIX production-process test")


def test_real_background_process_autostart_status_shutdown_restart(tmp_path):
    root = Path(__file__).resolve().parents[1]
    # AF_UNIX paths are short (typically <= 108 bytes), so use a deliberately
    # short isolated HOME rather than pytest's long nested tmp_path.
    short_root = Path("/tmp") / f"ca-{uuid4().hex[:10]}"
    home = short_root / "home"
    home.mkdir(parents=True)
    runtime_dir = home / ".caldav-assistant" / "runtime"
    log_path = tmp_path / "service.log"
    env = os.environ.copy()
    env["HOME"] = str(home)
    endpoint = "caldav-assistant-v1"
    processes = []

    def launch():
        log = log_path.open("ab", buffering=0)
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "caldav_assistant.internal.runtime.service"],
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        processes.append(process)
        return process

    client = RuntimeClient(
        UnixSocketIPCClient(endpoint, state_dir=runtime_dir, timeout=0.5),
        launch,
        request_timeout=1.0,
        startup_timeout=4.0,
        poll_interval=0.05,
    )

    try:
        assert client.status()["status"] == "stopped"
        first = client.ensure_running()
        assert first["status"] == "running"
        assert first["maintenance_alive"] is True
        first_pid = first["pid"]
        assert processes[-1].pid == first_pid
        assert (runtime_dir / f"{endpoint}.sock").exists()
        assert (runtime_dir / "ipc.auth").exists()

        # The production background loop must be wired to the durable Outbox, not
        # the scaffold stub that rejected pending(limit=...).
        from time import monotonic, sleep
        deadline = monotonic() + 1.0
        observed = first
        while (
            "wordpress.flush" not in observed.get("last_success", {})
            and monotonic() < deadline
        ):
            sleep(0.02)
            observed = client.status()
        assert "wordpress.flush" in observed.get("last_success", {})
        assert "wordpress.flush" not in observed.get("last_errors", {})

        assert client.stop(timeout=4.0) is True
        assert processes[-1].wait(timeout=4.0) == 0
        assert client.status()["status"] == "stopped"
        assert not (runtime_dir / f"{endpoint}.sock").exists()

        second = client.ensure_running()
        assert second["status"] == "running"
        assert len(processes) == 2
        assert second["pid"] == processes[-1].pid
        assert second["pid"] != first_pid
        assert client.stop(timeout=4.0) is True
        assert processes[-1].wait(timeout=4.0) == 0
        assert not (runtime_dir / f"{endpoint}.sock").exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
        shutil.rmtree(short_root, ignore_errors=True)

    text = log_path.read_text(errors="replace") if log_path.exists() else ""
    assert "found in sys.modules after import of package" not in text
    assert "Exception in thread caldav-assistant-maintenance" not in text
    assert "pending() got an unexpected keyword argument 'limit'" not in text


def test_production_cli_background_command_does_not_autostart_on_status_and_can_start_stop(
    tmp_path,
    monkeypatch,
):
    root = Path(__file__).resolve().parents[1]
    short_root = Path("/tmp") / f"ca-cli-{uuid4().hex[:8]}"
    home = short_root / "home"
    home.mkdir(parents=True)
    runtime_dir = home / ".caldav-assistant" / "runtime"
    endpoint = "caldav-assistant-v1"

    monkeypatch.setenv("HOME", str(home))
    current_pythonpath = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(root) + (os.pathsep + current_pythonpath if current_pythonpath else ""),
    )

    from caldav_assistant.internal.bootstrap import build_cli_application
    from caldav_assistant.internal.cli.app import run_cli

    app = build_cli_application()
    try:
        assert run_cli(["background", "status"], app=app) == 0
        assert app.runtime.status()["status"] == "stopped"
        assert not (runtime_dir / f"{endpoint}.sock").exists()

        assert run_cli(["background", "start"], app=app) == 0
        running = app.runtime.status()
        assert running["status"] == "running"
        assert running["maintenance_alive"] is True
        assert (runtime_dir / f"{endpoint}.sock").exists()

        assert run_cli(["background", "stop"], app=app) == 0
        assert app.runtime.status()["status"] == "stopped"
        assert not (runtime_dir / f"{endpoint}.sock").exists()
    finally:
        try:
            app.runtime.stop(timeout=2.0)
        except Exception:
            pass
        shutil.rmtree(short_root, ignore_errors=True)
