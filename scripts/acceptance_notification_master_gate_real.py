from __future__ import annotations

import os
from pathlib import Path
import tempfile

from caldav_assistant.internal.bootstrap import build_service_application
from caldav_assistant.internal.settings.keys import NOTIFICATIONS_ENABLED


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="caldav-notification-gate-") as raw:
        root = Path(raw)
        home = root / "home"
        bindir = root / "bin"
        home.mkdir()
        bindir.mkdir()
        log = root / "notify.log"

        fake = bindir / "notify-send"
        fake.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$CALDAV_NOTIFY_TEST_LOG\"\n"
        )
        fake.chmod(0o755)

        old_home = os.environ.get("HOME")
        old_path = os.environ.get("PATH")
        old_log = os.environ.get("CALDAV_NOTIFY_TEST_LOG")
        try:
            os.environ["HOME"] = str(home)
            os.environ["PATH"] = str(bindir) + os.pathsep + (old_path or "")
            os.environ["CALDAV_NOTIFY_TEST_LOG"] = str(log)

            app = build_service_application()

            # The hotfix must be safe-off on first upgraded startup even if callers
            # never visited Settings.
            assert app.ctx.settings.get(NOTIFICATIONS_ENABLED) is False
            app.ctx.notifications.send("blocked-default", "must not spawn notify-send")
            assert _read_lines(log) == []
            print("PASS: first hotfix startup is notifications-safe-off")

            app.ctx.settings.set(NOTIFICATIONS_ENABLED, True)
            app.ctx.notifications.send("allowed", "one real adapter invocation")
            lines = _read_lines(log)
            assert len(lines) == 1
            assert "allowed" in lines[0]
            print("PASS: explicit enable reaches the real Linux notify-send adapter")

            app.ctx.settings.set(NOTIFICATIONS_ENABLED, False)
            app.ctx.notifications.send("blocked-live", "must not reach adapter")
            assert _read_lines(log) == lines
            print("PASS: live notifications.enabled=false is an authoritative master gate")

            # Build again against the same HOME/SQLite. The one-time migration marker
            # must not keep overriding a later explicit choice.
            app.ctx.settings.set(NOTIFICATIONS_ENABLED, True)
            app2 = build_service_application()
            assert app2.ctx.settings.get(NOTIFICATIONS_ENABLED) is True
            app2.ctx.notifications.send("allowed-after-migration", "still enabled")
            assert len(_read_lines(log)) == 2
            print("PASS: one-time safety migration does not override later explicit enable")
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
            if old_log is None:
                os.environ.pop("CALDAV_NOTIFY_TEST_LOG", None)
            else:
                os.environ["CALDAV_NOTIFY_TEST_LOG"] = old_log

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
