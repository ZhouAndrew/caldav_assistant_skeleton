#!/usr/bin/env python3
"""Real installed-CLI acceptance for Extension runtime/persistence semantics.

This exercises the packaged user commands as separate CLI processes:
new -> disabled, reload -> temporary loaded, fresh process -> still disabled.
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

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-extension-lifecycle-") as raw:
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
            print("PASS: new Easy API extension starts persistently disabled")

            reloaded = _run(
                executable,
                root,
                env,
                "extension",
                "reload",
                "reload_guard",
            )
            if "reload_guard: loaded" not in reloaded:
                raise AssertionError(
                    "reload did not temporarily load the disabled extension"
                )
            print("PASS: reload temporarily loaded the disabled extension")

            # This is a fresh installed CLI process. The temporary reload must not have
            # changed the persisted Enabled preference.
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
                    "temporary reload unexpectedly persisted enablement"
                )
            print("PASS: fresh CLI process kept the extension persistently disabled")

            enabled = _run(
                executable,
                root,
                env,
                "extension",
                "enable",
                "reload_guard",
            )
            if "reload_guard: loaded" not in enabled:
                raise AssertionError("enable did not load the extension")
            print("PASS: explicit enable loads and persists the extension")

            info_after_enable = _run(
                executable,
                root,
                env,
                "extension",
                "info",
                "reload_guard",
            )
            if "Enabled: yes" not in info_after_enable:
                raise AssertionError("explicit enable was not persisted")
            print("PASS: fresh CLI process sees Enabled: yes")
            print("REAL INSTALLED EXTENSION LIFECYCLE ACCEPTANCE: PASS")
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
