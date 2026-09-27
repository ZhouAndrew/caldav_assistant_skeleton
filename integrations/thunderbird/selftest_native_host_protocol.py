#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
HOST = ROOT / "native_host.py"


def send(proc: subprocess.Popen[bytes], payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(struct.pack("<I", len(data)))
    proc.stdin.write(data)
    proc.stdin.flush()

    raw = proc.stdout.read(4)
    if len(raw) != 4:
        raise AssertionError(f"short response header: {raw!r}")
    size = struct.unpack("<I", raw)[0]
    body = proc.stdout.read(size)
    if len(body) != size:
        raise AssertionError("short response body")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("native host returned a non-object")
    return value


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="caldav-assistant-native-host-") as home:
        env = dict(os.environ)
        env["HOME"] = home
        proc = subprocess.Popen(
            [sys.executable, str(HOST)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            first = send(proc, {"command": "ping"})
            second = send(proc, {"command": "ping"})
            assert first["ok"] is True
            assert second["ok"] is True
            assert proc.poll() is None, "host exited between messages"

            content = b"0123456789" * 1000
            begin = send(
                proc,
                {
                    "command": "attachment_begin",
                    "task_id": "selftest-task",
                    "filename": "sample.bin",
                    "mime_type": "application/octet-stream",
                    "at": "2026-09-27T12:00:00+08:00",
                    "total_size": len(content),
                    "calendar_link": True,
                    "attachment_link": False,
                },
            )
            upload_id = begin["upload_id"]
            split = len(content) // 2
            for chunk in (content[:split], content[split:]):
                response = send(
                    proc,
                    {
                        "command": "attachment_chunk",
                        "upload_id": upload_id,
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
                assert response["ok"] is True

            aborted = send(
                proc,
                {
                    "command": "attachment_abort",
                    "upload_id": upload_id,
                },
            )
            assert aborted["ok"] is True
            assert aborted["aborted"] is True

            staged = Path(home) / ".caldav-assistant" / "thunderbird-attachments"
            leftovers = list(staged.glob("*")) if staged.exists() else []
            assert leftovers == [], f"incomplete upload files leaked: {leftovers}"

            assert proc.stdin is not None
            proc.stdin.close()
            returncode = proc.wait(timeout=5)
            assert returncode == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    print("Native host protocol selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
