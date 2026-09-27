from __future__ import annotations

import hashlib
import json
from pathlib import Path
import py_compile
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
THUNDERBIRD = ROOT / "integrations" / "thunderbird"


def test_manifest_declares_native_messaging_and_stable_extension_id():
    manifest = json.loads((THUNDERBIRD / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 2
    assert "nativeMessaging" in manifest["permissions"]
    gecko = manifest["browser_specific_settings"]["gecko"]
    assert gecko["id"] == "caldav-assistant-experimental@zhouandrew.local"
    assert gecko["strict_min_version"] == "115.0"
    assert gecko["update_url"] == (
        "https://andrew.local:17443/experimental/updates.json"
    )


def test_native_host_is_valid_python():
    py_compile.compile(str(THUNDERBIRD / "native_host.py"), doraise=True)


def test_xpi_contains_only_extension_runtime_files(tmp_path, monkeypatch):
    script = (THUNDERBIRD / "build-xpi.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(THUNDERBIRD / "build-xpi.py")}
    exec(compile(script, str(THUNDERBIRD / "build-xpi.py"), "exec"), namespace)

    manifest = json.loads((THUNDERBIRD / "manifest.json").read_text(encoding="utf-8"))
    xpi = THUNDERBIRD / "dist" / f"caldav-assistant-thunderbird-{manifest['version']}.xpi"
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


def test_native_host_is_side_by_side_and_does_not_use_production_runtime_client():
    source = (THUNDERBIRD / "native_host.py").read_text(encoding="utf-8")
    assert "build_service_application" in source
    assert "build_cli_application" not in source
    assert ".runtime.call(" not in source


def test_experimental_installer_uses_its_own_venv_and_does_not_replace_cli():
    source = (THUNDERBIRD / "install-native-host.sh").read_text(encoding="utf-8")
    assert "caldav-assistant-thunderbird-experimental" in source
    assert 'HOST_NAME="local.caldav_assistant_experimental"' in source
    assert 'EXT_ID="caldav-assistant-experimental@zhouandrew.local"' in source
    assert 'VENV_DIR="$BASE_DIR/venv"' in source
    assert 'pip install --upgrade "$ROOT"' in source
    assert "command -v caldav-assistant" not in source
    assert "build_service_application()" not in source
    assert "Production caldav-assistant was not replaced." in source


def test_space_uses_persistent_native_port_and_chunked_attachments():
    source = (THUNDERBIRD / "assistant.js").read_text(encoding="utf-8")
    assert "connectNative(HOST)" in source
    assert "sendNativeMessage" not in source
    assert "ATTACHMENT_CHUNK_BYTES = 256 * 1024" in source
    assert 'command: "attachment_begin"' in source
    assert 'command: "attachment_chunk"' in source
    assert 'command: "attachment_finish"' in source


def test_native_host_has_chunk_lifecycle_and_retries_outbox_on_open():
    source = (THUNDERBIRD / "native_host.py").read_text(encoding="utf-8")
    for name in (
        "attachment_begin",
        "attachment_chunk",
        "attachment_finish",
        "attachment_abort",
    ):
        assert f"def {name}(" in source
    assert 'core_call("wordpress.flush")' in source


def test_thunderbird_picker_reuses_core_actionable_semantics_and_state_actions():
    host = (THUNDERBIRD / "native_host.py").read_text(encoding="utf-8")
    source = (THUNDERBIRD / "assistant.js").read_text(encoding="utf-8")

    assert "tasks.list(actionable=True)" in host
    assert 'task.status === "COMPLETED"' not in source
    assert 'task.status === "CANCELLED"' not in source
    assert 'start.textContent = "继续"' in source
    assert 'start.textContent = "开始"' in source
    assert 'pause.hidden = false' in source


def test_self_hosted_update_feed_matches_manifest_and_xpi():
    manifest = json.loads((THUNDERBIRD / "manifest.json").read_text(encoding="utf-8"))
    subprocess.run(
        [sys.executable, str(THUNDERBIRD / "build-update-feed.py")],
        cwd=ROOT,
        check=True,
    )

    version = manifest["version"]
    addon_id = manifest["browser_specific_settings"]["gecko"]["id"]
    site = THUNDERBIRD / "dist" / "update-site" / "experimental"
    xpi = site / f"caldav-assistant-thunderbird-{version}.xpi"
    updates = json.loads((site / "updates.json").read_text(encoding="utf-8"))
    entry = updates["addons"][addon_id]["updates"][0]

    assert entry["version"] == version
    assert entry["update_link"] == (
        "https://andrew.local:17443/experimental/"
        f"{xpi.name}"
    )
    assert entry["update_hash"] == "sha256:" + hashlib.sha256(xpi.read_bytes()).hexdigest()
    assert entry["applications"]["gecko"]["strict_min_version"] == "115.0"


def test_standalone_update_server_isolated_from_existing_web_stack():
    publisher = (THUNDERBIRD / "publish-self-hosted-update.sh").read_text(encoding="utf-8")
    deploy = (THUNDERBIRD / "update-server" / "deploy.sh").read_text(encoding="utf-8")
    caddy = (THUNDERBIRD / "update-server" / "Caddyfile").read_text(encoding="utf-8")

    assert "/var/www" not in publisher
    assert "wordpress" not in publisher.casefold()
    assert "apache" not in publisher.casefold()
    assert "caldav-assistant-thunderbird-update-server" in deploy
    assert "--restart unless-stopped" in deploy
    assert 'caddy:2-alpine' in deploy
    assert 'PORT="17443"' in deploy
    assert 'HOSTNAME="andrew.local"' in deploy
    assert "update-ca-certificates" in deploy
    assert "certutil -A" in deploy
    assert "https://andrew.local:17443" in caddy
    assert "tls internal" in caddy
    assert 'manifest_json="$(curl --fail --silent --show-error "$UPDATE_URL")"' in publisher
    assert 'curl --fail --silent --show-error --head "$xpi_url"' in publisher
