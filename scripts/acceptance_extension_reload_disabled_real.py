#!/usr/bin/env python3
"""Real installed-CLI acceptance for disabled Extension reload semantics.

This drives the packaged user-facing commands, not ExtensionManager directly:
create a new disabled Easy API extension, reload it, and verify that reload does
not execute/enable code behind the user's back.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def _run(executable: str, root: Path, env: dict[str, str], *args: str) -> str:
    result = subprocess.run(
        [executable, *args],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    output = result.stdout or ""
    print(f"$ caldav-assistant {' '.join(args)}")
    print(output.rstrip())
    if result.returncode != 0:
        raise AssertionError(
            f"command {' '.join(args)!r} exited with {result.returncode}"
        )
    return output


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-extension-reload-") as raw:
        home = Path(raw) / "home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"

        try:
            created = _run(
                executable,
                root,
                env,
                "extension",
                "new",
                "reload_guard",
                "command",
            )
            if "reload_guard" not in created or "disabled" not in created:
                raise AssertionError("new extension was not created disabled")
            print("PASS: installed CLI created a disabled Easy API extension")

            reloaded = _run(
                executable,
                root,
                env,
                "extension",
                "reload",
                "reload_guard",
            )
            if "reload_guard: disabled" not in reloaded:
                raise AssertionError(
                    "reloading a disabled extension activated it; expected disabled"
                )
            if "reload_guard: loaded" in reloaded:
                raise AssertionError("disabled extension was loaded by reload")
            print("PASS: reload preserved disabled state")

            info = _run(
                executable,
                root,
                env,
                "extension",
                "info",
                "reload_guard",
            )
            if "Status: disabled" not in info or "Enabled: no" not in info:
                raise AssertionError(
                    "extension info no longer reports disabled/no after reload"
                )
            print("PASS: installed CLI reports disabled/no after reload")
            print("REAL INSTALLED DISABLED EXTENSION RELOAD ACCEPTANCE: PASS")
            return 0
        finally:
            subprocess.run(
                [executable, "background", "stop"],
                cwd=root,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
