#!/usr/bin/env python3
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist"
OUT.mkdir(exist_ok=True)
TARGET = OUT / "caldav-assistant-thunderbird-0.1.0.xpi"
FILES = [
    "manifest.json",
    "background.js",
    "assistant.html",
    "assistant.css",
    "assistant.js",
]

with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in FILES:
        archive.write(ROOT / name, name)

print(TARGET)
