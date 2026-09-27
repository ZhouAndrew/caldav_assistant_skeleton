from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

from caldav_assistant.internal.thunderbird.native_host import EXTENSION_ID, HOST_NAME


def test_thunderbird_manifest_and_native_host_contract_match():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "thunderbird_extension" / "manifest.json").read_text())

    assert manifest["browser_specific_settings"]["gecko"]["id"] == EXTENSION_ID
    assert "nativeMessaging" in manifest["permissions"]

    background = (root / "thunderbird_extension" / "background.js").read_text()
    assert HOST_NAME in background
    page = (root / "thunderbird_extension" / "assistant.html").read_text()
    for action in ("start", "pause", "cancel", "complete"):
        assert f'data-action="{action}"' in page


def test_builder_produces_installable_xpi_with_manifest_at_archive_root(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "scripts/build_thunderbird_xpi.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    xpi = root / "dist" / "caldav-assistant-thunderbird.xpi"
    assert xpi.is_file()

    with zipfile.ZipFile(xpi) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "assistant.html" in names
        assert "assistant.js" in names
        assert "background.js" in names
        assert all(not name.startswith("thunderbird_extension/") for name in names)
