#!/usr/bin/env python3
"""Installed-client acceptance for Extension lifecycle and the Easy API surface.

This is intentionally a real user extension flow, not direct ExtensionManager calls:
create -> edit source -> enable -> execute -> edit -> reload -> execute -> disable,
plus command-collision rejection and import-failure isolation.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from caldav_assistant.internal.settings.keys import (
    EXTENSIONS_ENABLED,
    NOTIFICATIONS_ENABLED,
    WORDPRESS_ENABLED,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import SQLiteKeyValueRepository, SQLiteStore


NAME = "acceptance_easy"
BROKEN = "acceptance_broken"


def _configure(home: Path) -> None:
    state_dir = home / ".caldav-assistant"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(state_dir / "assistant.sqlite3")
    store.migrate()
    settings = SettingsService(SQLiteKeyValueRepository(store, "settings"))
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False},
    )


def _run(executable: str, root: Path, env: dict[str, str], *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        [executable, *args],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    output = completed.stdout or ""
    print("$ " + " ".join(["caldav-assistant", *args]))
    print(output.rstrip())
    if "Traceback (most recent call last)" in output:
        raise AssertionError(f"User-visible traceback from {' '.join(args)}:\n{output}")
    return completed.returncode, output


def _contains(output: str, marker: str, label: str) -> None:
    if marker.casefold() not in output.casefold():
        raise AssertionError(f"Missing {marker!r} for {label}:\n{output}")
    print(f"PASS: {label}")


def _must_succeed(code: int, output: str, label: str) -> None:
    if code != 0:
        raise AssertionError(f"{label} returned {code}:\n{output}")
    print(f"PASS: {label}")


def _source(marker: str) -> str:
    return f'''from caldav_assistant.easy import command, show\n\n\n@command({NAME!r})\ndef run():\n    show({marker!r})\n'''


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-ext-real-") as raw_tmp:
        home = Path(raw_tmp) / "home"
        home.mkdir()
        _configure(home)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        extension_root = home / ".caldav-assistant" / "extensions"

        code, output = _run(executable, root, env, "extension", "new", NAME)
        _must_succeed(code, output, "one-file Easy API extension created through CLI")
        _contains(output, "disabled", "new executable code is not silently enabled")
        source_path = extension_root / f"{NAME}.py"
        if not source_path.is_file():
            raise AssertionError(f"Starter extension file missing: {source_path}")
        starter = source_path.read_text(encoding="utf-8")
        if "caldav_assistant.easy" not in starter or "@command" not in starter:
            raise AssertionError("Starter extension is not based on the frozen Easy API")
        print("PASS: generated starter is a real one-file Easy API extension")

        source_path.write_text(_source("EASY API HUMAN PATH V1"), encoding="utf-8")
        code, output = _run(executable, root, env, "extension", "enable", NAME)
        _must_succeed(code, output, "extension enable command completed")
        _contains(output, "loaded", "enabled extension was actually imported")

        code, output = _run(executable, root, env, NAME)
        _must_succeed(code, output, "Easy API extension command executed in a new process")
        _contains(output, "EASY API HUMAN PATH V1", "Easy show() reached ordinary client output")

        source_path.write_text(_source("EASY API HUMAN PATH V2"), encoding="utf-8")
        code, output = _run(executable, root, env, "extension", "reload", NAME)
        _must_succeed(code, output, "extension reload command completed")
        _contains(output, "loaded", "reload re-imported edited source")
        code, output = _run(executable, root, env, NAME)
        _must_succeed(code, output, "reloaded Easy API command executed")
        _contains(output, "EASY API HUMAN PATH V2", "new source is visible after reload")

        # Built-in command names are protected. The exact process exit convention is
        # less important than the user-visible rejection and absence of a new file.
        _, output = _run(executable, root, env, "extension", "new", "today")
        _contains(output, "already exists", "core command collision is rejected explicitly")
        if (extension_root / "today.py").exists():
            raise AssertionError("Conflicting extension source was created despite rejection")
        print("PASS: protected core command was not overwritten")

        # A broken import must become an extension error record, not a process crash.
        broken_path = extension_root / f"{BROKEN}.py"
        broken_path.write_text(
            "raise RuntimeError('deliberate extension acceptance failure')\n",
            encoding="utf-8",
        )
        code, output = _run(executable, root, env, "extension", "enable", BROKEN)
        _must_succeed(code, output, "broken extension failure was isolated into a record")
        _contains(output, "error", "broken extension is visibly marked error")
        _contains(output, "RuntimeError", "broken extension error type is visible")

        code, output = _run(executable, root, env, "extension", "errors", BROKEN)
        _must_succeed(code, output, "extension diagnostics remain usable after failed import")
        _contains(output, "deliberate extension acceptance failure", "diagnostics retain the real failure")

        code, output = _run(executable, root, env, "extensions")
        _must_succeed(code, output, "core extensions command still works with broken code present")
        _contains(output, NAME, "healthy extension remains discoverable")
        _contains(output, BROKEN, "broken extension remains isolated and inspectable")

        code, output = _run(executable, root, env, "extension", "disable", NAME)
        _must_succeed(code, output, "healthy extension can be disabled")
        _contains(output, "disabled", "disabled state is visible")
        _, output = _run(executable, root, env, NAME)
        if "EASY API HUMAN PATH V2" in output:
            raise AssertionError("Disabled extension command remained executable")
        _contains(output, "Unknown command", "disabled command is no longer in registry")

        code, output = _run(executable, root, env, "extension", "disable", BROKEN)
        _must_succeed(code, output, "broken extension can be disabled without crashing Core")
        code, output = _run(executable, root, env, "extension", "errors")
        _must_succeed(code, output, "error view still works after cleanup")

        print("REAL EXTENSION / EASY API HUMAN-PATH ACCEPTANCE: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
