#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile


EXPECTED_ID = "caldav-assistant-experimental@zhouandrew.local"
EXPECTED_NAME = "CalDAV Assistant Experimental"
REQUIRED_FILES = {
    "manifest.json",
    "background.js",
    "assistant.html",
    "assistant.css",
    "assistant.js",
    "experiments/assistantCalendar/schema.json",
    "experiments/assistantCalendar/parent.js",
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"XPI identity check failed: {message}")


def verify(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"not a file: {path}")

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = sorted(REQUIRED_FILES - names)
            if missing:
                fail(f"missing workspace runtime files: {', '.join(missing)}")

            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            background = archive.read("background.js").decode("utf-8")
            html = archive.read("assistant.html").decode("utf-8")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(str(exc))

    gecko = manifest.get("browser_specific_settings", {}).get("gecko", {})
    if manifest.get("name") != EXPECTED_NAME:
        fail(
            f"wrong add-on name {manifest.get('name')!r}; "
            f"expected {EXPECTED_NAME!r}"
        )
    if gecko.get("id") != EXPECTED_ID:
        fail(
            f"wrong add-on id {gecko.get('id')!r}; "
            f"expected {EXPECTED_ID!r}"
        )

    permissions = set(manifest.get("permissions") or [])
    if "nativeMessaging" not in permissions:
        fail("nativeMessaging permission is missing")
    if "assistantCalendar" not in (manifest.get("experiment_apis") or {}):
        fail("assistantCalendar Experiment API is missing")

    if "messenger.spaces.create" not in background:
        fail("Thunderbird Space creation code is missing")

    for tab in ("work", "record", "today", "diagnostics"):
        if f'data-tab="{tab}"' not in html:
            fail(f"workspace tab is missing: {tab}")
    for action in ("start", "pause", "cancel", "complete"):
        if f'id="action-{action}"' not in html:
            fail(f"CalDAV work action is missing: {action}")

    version = str(manifest.get("version") or "")
    if not version:
        fail("manifest version is empty")

    return {
        "name": EXPECTED_NAME,
        "id": EXPECTED_ID,
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refuse to hand off an XPI unless it is the CalDAV Assistant workspace."
    )
    parser.add_argument("xpi", type=Path)
    args = parser.parse_args()

    result = verify(args.xpi)
    print(
        "CalDAV Assistant XPI identity: OK "
        f"(name={result['name']!r}, id={result['id']}, version={result['version']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
