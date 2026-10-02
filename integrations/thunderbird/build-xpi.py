#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist"
OUT.mkdir(exist_ok=True)

MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
VERSION = str(MANIFEST["version"])
TARGET = OUT / f"caldav-assistant-thunderbird-{VERSION}.xpi"
FILES = [
    "manifest.json",
    "background.js",
    "assistant.html",
    "assistant.css",
    "assistant.js",
    "refresh_core.js",
    "experiments/assistantCalendar/schema.json",
    "experiments/assistantCalendar/parent.js",
]


with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in FILES:
        archive.write(ROOT / name, name)

print(TARGET)
