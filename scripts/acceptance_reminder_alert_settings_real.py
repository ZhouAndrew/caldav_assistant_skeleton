#!/usr/bin/env python3
"""Real PTY acceptance for reminder-alert settings and extension creation.

This is deliberately a human-path check, not a schema/unit test. It launches the
installed ``caldav-assistant settings`` command in a real pseudo-terminal, uses the
numbered Settings menus a person sees, changes reminder controls, acknowledges a real
persistent terminal alarm with Ctrl-C, creates a small Easy API extension through the
wizard, and enables it through the same UI.
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
            _expect(child, "Agenda", label="Agenda settings are reachable from the root")
            _expect(child, "Developer", label="Developer tools are reachable from the root")
            child.sendline("3")

            _expect(child, "Notifications & sound", label="rich Notifications panel opened")
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
            _expect(child, "Test terminal bell", label="real bell test is visible")
            _expect(
                child,
                "How persistent acknowledgement works",
                label="persistent acknowledgement behavior is discoverable",
            )

            child.sendline("4")
            _expect(child, "Terminal bell rings per reminder", label="ring-count preset menu opened")
            child.sendline("5")
            _expect(
                child,
                "✓ Terminal bell rings per reminder: 5",
                label="ring count changed through the ordinary human menu",
            )

            child.sendline("5")
            _expect(child, "Pause between bell rings", label="bell-interval preset menu opened")
            child.sendline("2")
            _expect(
                child,
                "✓ Pause between bell rings \(ms\): 200",
                label="bell interval changed through the ordinary human menu",
            )

            child.sendline("3")
            _expect(child, "Terminal bell", label="terminal-bell On/Off menu opened")
            child.sendline("2")
            _expect(child, "✓ Terminal bell: Off", label="terminal bell can be disabled")

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

            # One logical BEL emitted by Settings must become a persistent alarm.
            # Observing BEL #4 proves a second burst began.
            child.sendline("6")
            _expect(child, "Testing the terminal reminder alarm", label="bell test started from Settings")
            _expect(
                child,
                "Reminder alarm — press Ctrl-C to stop the ringing",
                label="persistent alarm announced acknowledgement",
            )
            for bell_number in range(4):
                child.expect("\a")
                print(f"PASS: Settings bell test emitted terminal BEL #{bell_number + 1}")
            child.sendcontrol("c")
            _expect(child, "Reminder alarm stopped", label="real Ctrl-C acknowledged Settings bell test")
            _expect(
                child,
                "Task/Event state was not changed",
                label="bell acknowledgement remained presentation-only",
            )
            _expect(child, "Notifications & sound", label="Settings remained usable after alarm acknowledgement")

            child.sendline("0")
            _expect(child, "Settings", label="Back returns to Settings root")

            # Extensions is item 7 in the richer Settings root. Create a real small
            # Task template through the numbered wizard and enable it immediately.
            child.sendline("7")
            _expect(child, "Extensions", label="Extensions management panel opened")
            _expect(child, "Create user extension", label="extension creation is visible")
            _expect(child, "Extension folder", label="extension folder is discoverable")
            _expect(child, "Prepare editor workspace", label="editor setup is discoverable")
            child.sendline("2")

            _expect(child, "Choose extension template", label="extension template wizard opened")
            _expect(child, "Command — add one small command", label="Command template is offered")
            _expect(child, "Task automation — choose and start a Task", label="Task template is offered")
            _expect(child, "Reminder — ask when and create a reminder", label="Reminder template is offered")
            _expect(child, "Daily workflow — show today's Agenda", label="Daily template is offered")
            _expect(child, "Empty Easy API — smallest possible file", label="Empty template is offered")
            child.sendline("2")

            _expect(child, "Extension name for create", label="wizard asks for extension name")
            child.sendline("accept-task-template")
            _expect(
                child,
                "Created typed Easy API extension accept-task-template",
                label="small Task template was really created",
            )
            _expect(child, "Extension created disabled", label="safe disabled-by-default lifecycle is explicit")
            child.sendline("1")
            _expect(child, "accept-task-template: loaded", label="wizard enabled the new extension")
            _expect(child, "Extensions", label="wizard returned to extension management")

            child.sendline("0")
            _expect(child, "Settings", label="Extensions Back returns to Settings root")
            child.sendline("0")
            child.expect(pexpect.EOF)
            if child.exitstatus not in (None, 0):
                raise AssertionError(f"caldav-assistant settings exited with {child.exitstatus}")

            restored_settings = _settings_for_home(home)
            if restored_settings.get(TERMINAL_BELL_ENABLED) is not True:
                raise AssertionError("Terminal bell was not restored to On")
            if restored_settings.get(TERMINAL_BELL_REPEAT_COUNT) != 3:
                raise AssertionError("Terminal bell repeat count was not restored to 3")
            if restored_settings.get(TERMINAL_BELL_INTERVAL_MS) != 400:
                raise AssertionError("Terminal bell interval was not restored to 400 ms")
            print("PASS: persisted reminder-alert settings match the restored UI values")

            matches = list(home.rglob("accept-task-template.py"))
            if len(matches) != 1:
                raise AssertionError(
                    f"Expected one generated extension source, found {len(matches)}"
                )
            source = matches[0].read_text(encoding="utf-8")
            compile(source, str(matches[0]), "exec")
            if "choose_task" not in source or "start(task)" not in source:
                raise AssertionError("Generated Task template does not contain its Easy API bricks")
            if "caldav_assistant.internal" in source:
                raise AssertionError("Generated extension leaked internal APIs")
            if len(source.splitlines()) >= 25:
                raise AssertionError("Small Task template became unexpectedly large")
            print("PASS: generated extension is a small compilable public Easy API file")

            enabled_map = restored_settings.get(EXTENSIONS_ENABLED, {})
            if enabled_map.get("accept-task-template") is not True:
                raise AssertionError("Wizard enable action was not persisted")
            print("PASS: extension enablement from the real Settings wizard was persisted")

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
            print("REAL REMINDER ALERT SETTINGS + EXTENSION WIZARD ACCEPTANCE: PASS")
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
