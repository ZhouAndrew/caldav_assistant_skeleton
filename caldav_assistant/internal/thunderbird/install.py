"""Install the per-user Thunderbird Native Messaging host manifest."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import stat
import sys

from .native_host import EXTENSION_ID, HOST_NAME


def install() -> dict[str, str]:
    state_dir = Path.home() / ".caldav-assistant" / "thunderbird"
    state_dir.mkdir(parents=True, exist_ok=True)

    wrapper = state_dir / "native-host"
    wrapper.write_text(
        "#!/usr/bin/env sh\n"
        f"exec {shlex.quote(sys.executable)} -m "
        "caldav_assistant.internal.thunderbird.native_host\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    manifest_dir = Path.home() / ".mozilla" / "native-messaging-hosts"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_dir / f"{HOST_NAME}.json"
    manifest.write_text(
        json.dumps(
            {
                "name": HOST_NAME,
                "description": "CalDAV Assistant bridge for Thunderbird",
                "path": str(wrapper.resolve()),
                "type": "stdio",
                "allowed_extensions": [EXTENSION_ID],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "wrapper": str(wrapper),
        "manifest": str(manifest),
        "extension_id": EXTENSION_ID,
    }


def main() -> int:
    result = install()
    print("Thunderbird Native Messaging host installed.")
    print(f"Manifest: {result['manifest']}")
    print(f"Host: {result['wrapper']}")
    print(f"Extension ID: {result['extension_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
