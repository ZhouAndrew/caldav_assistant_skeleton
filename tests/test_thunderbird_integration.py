from __future__ import annotations

import json
from pathlib import Path
import py_compile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
THUNDERBIRD = ROOT / "integrations" / "thunderbird"


def test_manifest_declares_native_messaging_and_stable_extension_id():
    manifest = json.loads((THUNDERBIRD / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 2
    assert "nativeMessaging" in manifest["permissions"]
    assert manifest["applications"]["gecko"]["id"] == "caldav-assistant@zhouandrew.local"
    assert manifest["applications"]["gecko"]["strict_min_version"] == "115.0"


def test_native_host_is_valid_python():
    py_compile.compile(str(THUNDERBIRD / "native_host.py"), doraise=True)


def test_xpi_contains_only_extension_runtime_files(tmp_path, monkeypatch):
    script = (THUNDERBIRD / "build-xpi.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(THUNDERBIRD / "build-xpi.py")}
    exec(compile(script, str(THUNDERBIRD / "build-xpi.py"), "exec"), namespace)

    xpi = THUNDERBIRD / "dist" / "caldav-assistant-thunderbird-0.1.0.xpi"
    assert xpi.exists()
    with zipfile.ZipFile(xpi) as archive:
        names = set(archive.namelist())
    assert names == {
        "manifest.json",
        "background.js",
        "assistant.html",
        "assistant.css",
        "assistant.js",
    }
