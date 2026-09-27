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
    assert gecko["strict_min_version"] == "128.0"
    assert "clipboardWrite" in manifest["permissions"]
    assert manifest["experiment_apis"]["assistantCalendar"]["parent"]["paths"] == [
        ["assistantCalendar"]
    ]
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
        "experiments/assistantCalendar/schema.json",
        "experiments/assistantCalendar/parent.js",
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
    assert entry["applications"]["gecko"]["strict_min_version"] == "128.0"


def test_standalone_update_server_uses_python_stdlib_runtime():
    publisher = (THUNDERBIRD / "publish-self-hosted-update.sh").read_text(encoding="utf-8")
    deploy = (THUNDERBIRD / "update-server" / "deploy.sh").read_text(encoding="utf-8")
    server = (THUNDERBIRD / "update-server" / "server.py").read_text(encoding="utf-8")
    verifier = (THUNDERBIRD / "update-server" / "verify.py").read_text(encoding="utf-8")

    combined = "\n".join((publisher, deploy, server, verifier)).casefold()
    assert "/var/www" not in combined
    assert "wordpress" not in combined
    assert "apache" not in combined
    assert "docker" not in combined
    assert "caddy" not in combined

    assert "import http.server" in server
    assert "import ssl" in server
    assert "ThreadingHTTPServer" in server
    assert "application/x-xpinstall" in server
    assert 'PORT="17443"' in deploy
    assert 'HOSTNAME="andrew.local"' in deploy
    assert "systemctl --user enable --now" in deploy
    assert "Restart=on-failure" in deploy
    assert "openssl req -x509" in deploy
    assert "certutil -A" in deploy
    assert 'python3 "$VERIFY_PY"' in publisher


def test_python_update_server_sources_compile():
    for path in (
        THUNDERBIRD / "update-server" / "server.py",
        THUNDERBIRD / "update-server" / "verify.py",
        THUNDERBIRD / "update-server" / "selftest.py",
        THUNDERBIRD / "verify-installed-native-host.py",
        THUNDERBIRD / "setup_gui.py",
    ):
        py_compile.compile(str(path), doraise=True)


def test_thunderbird_fast_path_uses_local_task_collections_and_local_core_state():
    source = (THUNDERBIRD / "assistant.js").read_text(encoding="utf-8")
    host = (THUNDERBIRD / "native_host.py").read_text(encoding="utf-8")
    experiment = (
        THUNDERBIRD / "experiments" / "assistantCalendar" / "parent.js"
    ).read_text(encoding="utf-8")

    assert "messenger.assistantCalendar.listTasks()" in source
    assert 'host({command: "state"})' in source
    assert "onTasksChanged.addListener(scheduleTaskRefresh)" in source
    assert "getItemsAsArray" in experiment
    assert "ITEM_FILTER_TYPE_TODO" in experiment
    assert "cal.manager" in experiment
    assert ".getCalendars()" in experiment

    state_start = host.index("def state_snapshot()")
    snapshot_start = host.index("def snapshot()", state_start)
    state_source = host[state_start:snapshot_start]
    assert "list(actionable=True)" not in state_source
    assert "ensure_history_calendar()" not in state_source
    assert 'core_call("wordpress.flush")' not in state_source


def test_thunderbird_visible_logs_are_copyable_and_record_request_timings():
    html = (THUNDERBIRD / "assistant.html").read_text(encoding="utf-8")
    css = (THUNDERBIRD / "assistant.css").read_text(encoding="utf-8")
    source = (THUNDERBIRD / "assistant.js").read_text(encoding="utf-8")
    host = (THUNDERBIRD / "native_host.py").read_text(encoding="utf-8")

    assert 'id="logs"' in html
    assert 'id="copy-logs"' in html
    assert 'id="copy-today"' in html
    assert "user-select: text" in css
    assert "navigator.clipboard" in source
    assert 'command: "logs"' in source
    assert 'command: "logs_clear"' in source
    assert "native-host.log" in host
    assert '"task_action_ms"' in host
    assert '"wordpress_flush_ms"' in host
    assert '"calendar_link_ms"' in host


def test_update_feed_prunes_stale_generated_xpis():
    source = (THUNDERBIRD / "build-update-feed.py").read_text(encoding="utf-8")
    deploy = (THUNDERBIRD / "update-server" / "deploy.sh").read_text(encoding="utf-8")
    publish = (THUNDERBIRD / "publish-self-hosted-update.sh").read_text(encoding="utf-8")

    assert 'SITE.glob("caldav-assistant-thunderbird-*.xpi")' in source
    assert "stale.unlink()" in source
    assert 'XPI_NAME="$(python3 - "$SOURCE/updates.json"' in deploy
    assert 'XPI_NAME="$(python3 - "$SOURCE/updates.json"' in publish
    assert "Expected exactly one generated XPI" not in deploy
    assert "Expected exactly one generated XPI" not in publish


def test_interactive_setup_exposes_repair_and_log_verification():
    setup = (THUNDERBIRD / "setup.sh").read_text(encoding="utf-8")
    installer = (THUNDERBIRD / "install-native-host.sh").read_text(encoding="utf-8")

    assert "Full install/update (recommended)" in setup
    assert 'exec python3 "$HERE/setup_gui.py"' in setup
    assert "--terminal" in setup
    assert "Verify Native Host + log reachability" in setup
    assert "--verify" in setup
    assert "verify-installed-native-host.py" in setup
    assert "native-host.log" in setup
    assert "verify-installed-native-host.py" in installer
    assert 'ln -sfn "$LOG_PATH" "$BASE_DIR/native-host.log"' in installer


def test_log_panel_never_remains_indefinitely_loading():
    html = (THUNDERBIRD / "assistant.html").read_text(encoding="utf-8")
    source = (THUNDERBIRD / "assistant.js").read_text(encoding="utf-8")
    host = (THUNDERBIRD / "native_host.py").read_text(encoding="utf-8")

    assert 'id="open-log-folder"' in html
    assert 'id="copy-log-path"' in html
    assert "renderLogError" in source
    assert 'diagnosticHost({command: "logs", limit: 300}, 5000)' in source
    assert "ensureDiagnosticPort" in source
    assert "diagnosticPort = messenger.runtime.connectNative(HOST)" not in source
    assert "const port = messenger.runtime.connectNative(HOST)" in source
    assert "Promise.allSettled" in source
    assert 'command == "logs_open"' in host
    assert "open_log_folder" in host
    assert 'command not in {"logs", "logs_clear", "logs_open"}' in host


def test_setup_gui_exposes_simple_one_click_actions():
    source = (THUNDERBIRD / "setup_gui.py").read_text(encoding="utf-8")

    assert "Install / Update Everything" in source
    assert "Repair Native Host" in source
    assert "Repair Update Server" in source
    assert "Verify Everything" in source
    assert "Open Log Folder" in source
    assert "Live output" in source
    assert "threading.Thread" in source
    assert "scrolledtext.ScrolledText" in source
