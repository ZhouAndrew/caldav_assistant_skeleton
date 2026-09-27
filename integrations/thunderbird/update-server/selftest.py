#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
SERVER = HERE / "server.py"
VERIFY = HERE / "verify.py"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="tb-update-server-") as raw:
        root = Path(raw)
        web = root / "www"
        experimental = web / "experimental"
        experimental.mkdir(parents=True)
        cert = root / "test.crt"
        key = root / "test.key"

        xpi = experimental / "caldav-assistant-thunderbird-test.xpi"
        xpi.write_bytes(b"test-xpi")
        updates = {
            "addons": {
                "caldav-assistant-experimental@zhouandrew.local": {
                    "updates": [
                        {
                            "version": "999.0",
                            "update_link": (
                                f"https://andrew.local:{port}/experimental/{xpi.name}"
                            ),
                        }
                    ]
                }
            }
        }
        (experimental / "updates.json").write_text(
            json.dumps(updates), encoding="utf-8"
        )

        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=andrew.local",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-addext",
                "subjectAltName=DNS:andrew.local,IP:127.0.0.1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        proc = subprocess.Popen(
            [
                sys.executable,
                str(SERVER),
                "--root",
                str(web),
                "--cert",
                str(cert),
                "--key",
                str(key),
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            url = f"https://andrew.local:{port}/experimental/updates.json"
            for _ in range(40):
                run = subprocess.run(
                    [
                        sys.executable,
                        str(VERIFY),
                        "--url",
                        url,
                        "--ca",
                        str(cert),
                    ],
                    text=True,
                    capture_output=True,
                )
                if run.returncode == 0:
                    print(run.stdout.strip())
                    print("Standalone Python HTTPS server selftest: OK")
                    return 0
                if proc.poll() is not None:
                    out, err = proc.communicate()
                    raise RuntimeError(
                        f"Server exited early: rc={proc.returncode}\n{out}\n{err}"
                    )
                time.sleep(0.1)
            raise RuntimeError(f"Verifier never succeeded: {run.stderr}")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
