#!/usr/bin/env python3
"""Build the installable Thunderbird XPI from thunderbird_extension/."""
from __future__ import annotations

from pathlib import Path
import zipfile


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = root / "thunderbird_extension"
    target_dir = root / "dist"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "caldav-assistant-thunderbird.xpi"

    required = {
        "manifest.json",
        "background.js",
        "assistant.html",
        "assistant.css",
        "assistant.js",
        "icon.svg",
    }
    missing = [name for name in sorted(required) if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Missing Thunderbird extension files: {', '.join(missing)}")

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())

    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
