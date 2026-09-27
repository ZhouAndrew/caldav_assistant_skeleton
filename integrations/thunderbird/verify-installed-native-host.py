#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys


def send(proc: subprocess.Popen[bytes], payload: dict[str, object]) -> dict[str, object]:
    assert proc.stdin is not None
    assert proc.stdout is not None
    data = json.dumps(payload).encode("utf-8")
    proc.stdin.write(struct.pack("<I", len(data)))
    proc.stdin.write(data)
    proc.stdin.flush()

    raw = proc.stdout.read(4)
    if len(raw) != 4:
        raise RuntimeError(f"Native Host returned a short header: {raw!r}")
    size = struct.unpack("<I", raw)[0]
    body = proc.stdout.read(size)
    if len(body) != size:
        raise RuntimeError("Native Host returned a short body")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Native Host response is not an object")
    if value.get("ok") is False:
        raise RuntimeError(str(value.get("error") or "Native Host request failed"))
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("launcher", type=Path)
    args = parser.parse_args()

    launcher = args.launcher.expanduser().resolve()
    if not launcher.is_file():
        raise SystemExit(f"Native Host launcher not found: {launcher}")

    proc = subprocess.Popen(
        [str(launcher)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        ping = send(proc, {"command": "ping"})
        logs = send(proc, {"command": "logs", "limit": 5})

        if ping.get("name") != "CalDAV Assistant Thunderbird host":
            raise RuntimeError(f"Unexpected Native Host identity: {ping!r}")

        path = Path(str(logs.get("path") or "")).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Native Host log file is not reachable: {path}")
        if not path.parent.is_dir():
            raise RuntimeError(f"Native Host log directory is not reachable: {path.parent}")

        print("Native Host protocol: OK")
        print("Native Host logs: OK")
        print(f"Log path: {path}")
        return 0
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
