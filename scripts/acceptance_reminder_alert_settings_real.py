#!/usr/bin/env python3
"""Real PTY acceptance for reminder-alert settings.

This is deliberately a human-path check, not a schema/unit test.  It launches the
installed ``caldav-assistant settings`` command in a real pseudo-terminal, enters the
Notifications menu by number, changes reminder bell controls through the same menus a
person sees, observes the visible results, then restores the original effective values.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile

import pexpect

from caldav_assistant.internal.settings.keys import (
    EXTENSIONS_ENABLED,
    TERMINAL_BELL_ENABLED,
    TERMINAL_BELL_INTERVAL_MS,
    TERMINAL_BELL_REPEAT_COUNT,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import SQLiteKeyValueRepository, SQLiteStore


def _settings_for_home(home: Path) -> SettingsService:
    state_dir = home / ".caldav-assistant"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(state_dir / "assistant.sqlite3")
    store.migrate()
    return SettingsService(SQLiteKeyValueRepository(store, "settings"))


def _expect(child: pexpect.spawn, pattern: str, *, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-alert-settings-") as raw_tmp:
        home = Path(raw_tmp) / "home"
        home.mkdir()
        settings = _settings_for_home(home)
        settings.set(
            EXTENSIONS_ENABLED,
            {"software_intro": False, "wordpress_work_session_log": False},
        )

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        child: pexpect.spawn | None = None
        try:
            child = pexpect.spawn(
                executable,
                ["settings"],
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=20,
            )

            _expect(child, "Settings", label="installed Settings menu opened")
            _expect(child, "Notifications", label="Notifications category is visible")
            child.sendline("3")

            _expect(child, "Reminder sound: On", label="reminder sound has a readable On/Off control")
            _expect(child, "Terminal bell: On", label="terminal bell has a readable On/Off control")
            _expect(
                child,
                "Terminal bell rings per reminder: 3",
                label="default three-ring pattern is visible",
            )
            _expect(
                child,
                r"Pause between bell rings \(ms\): 400",
                label="bell interval includes its unit",
            )

            # Change the repeat count through menu presets.
            child.sendline("4")
            _expect(child, "Terminal bell rings per reminder", label="ring-count preset menu opened")
            child.sendline("5")
            _expect(
                child,
                "✓ Terminal bell rings per reminder: 5",
                label="ring count changed through the ordinary human menu",
            )

            # Change the interval through menu presets.
            child.sendline("5")
            _expect(child, "Pause between bell rings", label="bell-interval preset menu opened")
            child.sendline("2")
            _expect(
                child,
                "✓ Pause between bell rings \(ms\): 200",
                label="bell interval changed through the ordinary human menu",
            )

            # Verify the disable switch really exists in the same surface.
            child.sendline("3")
            _expect(child, "Terminal bell", label="terminal-bell On/Off menu opened")
            child.sendline("2")
            _expect(child, "✓ Terminal bell: Off", label="terminal bell can be disabled")

            # Restore every changed value before leaving, just as a manual acceptance
            # check should leave a user's configuration unchanged.
            child.sendline("3")
            _expect(child, "Terminal bell", label="terminal-bell menu reopened for restore")
            child.sendline("1")
            _expect(child, "✓ Terminal bell: On", label="terminal bell restored to On")

            child.sendline("4")
            _expect(child, "Terminal bell rings per reminder", label="ring-count menu reopened for restore")
            child.sendline("3")
            _expect(child, "✓ Terminal bell rings per reminder: 3", label="ring count restored to three")

            child.sendline("5")
            _expect(child, "Pause between bell rings", label="interval menu reopened for restore")
            child.sendline("4")
            _expect(child, "✓ Pause between bell rings \(ms\): 400", label="bell interval restored to 400 ms")

            child.sendline("0")
            _expect(child, "Settings", label="Back returns to Settings root")
            child.sendline("0")
            child.expect(pexpect.EOF)
            if child.exitstatus not in (None, 0):
                raise AssertionError(f"caldav-assistant settings exited with {child.exitstatus}")

            # Read production settings storage after the real UI session.  This is not
            # the primary test; it proves the visible restore also restored persisted
            # effective behavior.
            restored_settings = _settings_for_home(home)
            if restored_settings.get(TERMINAL_BELL_ENABLED) is not True:
                raise AssertionError("Terminal bell was not restored to On")
            if restored_settings.get(TERMINAL_BELL_REPEAT_COUNT) != 3:
                raise AssertionError("Terminal bell repeat count was not restored to 3")
            if restored_settings.get(TERMINAL_BELL_INTERVAL_MS) != 400:
                raise AssertionError("Terminal bell interval was not restored to 400 ms")
            print("PASS: persisted reminder-alert settings match the restored UI values")

            stopped = subprocess.run(
                [executable, "background", "stop"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
            )
            if stopped.returncode != 0:
                raise AssertionError(f"background stop failed:\n{stopped.stdout}")
            print("PASS: real background Assistant stopped cleanly")
            print("REAL REMINDER ALERT SETTINGS ACCEPTANCE: PASS")
            return 0
        finally:
            if child is not None and child.isalive():
                child.close(force=True)
            try:
                subprocess.run(
                    [executable, "background", "stop"],
                    cwd=root,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
