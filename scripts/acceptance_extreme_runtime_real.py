#!/usr/bin/env python3
"""Extreme real-process lifecycle acceptance.

This intentionally attacks the production background lifecycle through the installed
CLI, not through mocks:
- many concurrent "background start" processes race on one isolated HOME;
- many concurrent status calls must observe one daemon PID;
- repeated restart must leave one live generation each time;
- SIGKILL must be recoverable through stale socket/lock cleanup;
- final stop must remove the production socket cleanly.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time


START_RACERS = 16
STATUS_RACERS = 24
RESTARTS = 8
PID_RE = re.compile(r"^PID:\s*(\d+)\s*$", re.MULTILINE)


def _run(executable: str, env: dict[str, str], *args: str, timeout: float = 15.0):
    return subprocess.run(
        [executable, *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def _pid(text: str) -> int:
    match = PID_RE.search(text)
    if not match:
        raise AssertionError(f"background output did not expose PID:\n{text}")
    return int(match.group(1))


def _wait_dead(pid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        time.sleep(0.05)
    raise AssertionError(f"PID {pid} did not exit within {timeout:.1f}s")


def main() -> int:
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("installed caldav-assistant is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-extreme-runtime-") as raw:
        home = Path(raw) / "home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        runtime_dir = home / ".caldav-assistant" / "runtime"
        socket_path = runtime_dir / "caldav-assistant-v1.sock"

        racers = [
            subprocess.Popen(
                [executable, "background", "start"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            for _ in range(START_RACERS)
        ]
        race_outputs = []
        for proc in racers:
            out, _ = proc.communicate(timeout=20)
            race_outputs.append((proc.returncode, out))
        failed = [(code, out) for code, out in race_outputs if code != 0]
        if failed:
            raise AssertionError(f"concurrent start failures: {failed[:3]!r}")

        status = _run(executable, env, "background", "status")
        if status.returncode != 0:
            raise AssertionError(status.stdout)
        first_pid = _pid(status.stdout)
        if not socket_path.exists():
            raise AssertionError("production socket missing after concurrent startup")
        print(f"PASS: {START_RACERS} concurrent starts converged on PID {first_pid}")

        def status_once(_: int):
            result = _run(executable, env, "background", "status")
            if result.returncode != 0:
                raise AssertionError(result.stdout)
            return _pid(result.stdout)

        with ThreadPoolExecutor(max_workers=STATUS_RACERS) as pool:
            pids = list(pool.map(status_once, range(STATUS_RACERS)))
        if set(pids) != {first_pid}:
            raise AssertionError(f"status calls saw multiple daemon PIDs: {sorted(set(pids))}")
        print(f"PASS: {STATUS_RACERS} concurrent status calls saw exactly one daemon")

        seen = {first_pid}
        previous = first_pid
        for index in range(RESTARTS):
            result = _run(executable, env, "background", "restart", timeout=20)
            if result.returncode != 0:
                raise AssertionError(f"restart {index + 1} failed:\n{result.stdout}")
            current = _pid(result.stdout)
            if current == previous:
                raise AssertionError(f"restart {index + 1} reused PID {current}")
            seen.add(current)
            previous = current
        print(f"PASS: {RESTARTS} repeated restarts produced clean new generations")

        os.kill(previous, signal.SIGKILL)
        _wait_dead(previous)
        # Deliberately do not delete socket/lock files. The production launcher must
        # distinguish a stale endpoint from a live generation and recover itself.
        recovery = _run(executable, env, "background", "start", timeout=20)
        if recovery.returncode != 0:
            raise AssertionError(f"recovery after SIGKILL failed:\n{recovery.stdout}")
        recovered_pid = _pid(recovery.stdout)
        if recovered_pid == previous:
            raise AssertionError("SIGKILL recovery reported the dead generation")
        print(f"PASS: abrupt kill recovered from PID {previous} to {recovered_pid}")

        with ThreadPoolExecutor(max_workers=STATUS_RACERS) as pool:
            recovered = list(pool.map(status_once, range(STATUS_RACERS)))
        if set(recovered) != {recovered_pid}:
            raise AssertionError(
                f"post-recovery status calls saw multiple PIDs: {sorted(set(recovered))}"
            )

        stop = _run(executable, env, "background", "stop", timeout=20)
        if stop.returncode != 0:
            raise AssertionError(stop.stdout)
        _wait_dead(recovered_pid)
        deadline = time.monotonic() + 3.0
        while socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if socket_path.exists():
            raise AssertionError("socket remained after graceful stop")

        log_path = runtime_dir / "service.log"
        if log_path.exists():
            log = log_path.read_text(encoding="utf-8", errors="replace")
            forbidden = (
                "Traceback (most recent call last)",
                "Exception in thread caldav-assistant-maintenance",
                "Address already in use",
            )
            for marker in forbidden:
                if marker in log:
                    raise AssertionError(f"service.log contains {marker!r}")

        print(
            "PASS: extreme runtime lifecycle completed "
            f"({START_RACERS} start racers, {STATUS_RACERS} status racers, "
            f"{RESTARTS} restarts, SIGKILL recovery)"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
