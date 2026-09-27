#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIST = HERE / "dist"
DIST.mkdir(exist_ok=True)

XPI = DIST / "caldav-assistant-thunderbird-0.1.0.xpi"
BUNDLE = DIST / "caldav-assistant-thunderbird-experimental-0.1.0.zip"


def main() -> int:
    subprocess.run(
        [sys.executable, str(HERE / "build-xpi.py")],
        cwd=ROOT,
        check=True,
    )

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-thunderbird-bundle-") as raw:
        staging = Path(raw)
        wheel_dir = staging / "wheel"
        wheel_dir.mkdir()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(ROOT),
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
            ],
            cwd=ROOT,
            check=True,
        )
        wheels = list(wheel_dir.glob("caldav_assistant-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected exactly one project wheel, found {wheels!r}")

        files = {
            HERE / "install-bundle.sh": "install.sh",
            HERE / "uninstall-experimental.sh": "uninstall.sh",
            HERE / "native_host.py": "native_host.py",
            XPI: XPI.name,
            wheels[0]: wheels[0].name,
        }

        with zipfile.ZipFile(BUNDLE, "w", zipfile.ZIP_DEFLATED) as archive:
            for source, target in files.items():
                archive.write(source, target)

    print(BUNDLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
