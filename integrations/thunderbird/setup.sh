#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
UPDATE_DEPLOY="$HERE/update-server/deploy.sh"
HOST_INSTALL="$HERE/install-native-host.sh"
HOST_VERIFY="$HERE/verify-installed-native-host.py"
HOST_LAUNCHER="$HOME/.local/bin/caldav-assistant-thunderbird-host-experimental"
STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"
UPDATE_VERIFY="$STATE_DIR/verify.py"
CA_CERT="$STATE_DIR/tls/ca.crt"
UPDATE_URL="https://andrew.local:17443/experimental/updates.json"
LOG_PATH="$HOME/.local/state/caldav-assistant/thunderbird/native-host.log"
SERVICE_NAME="caldav-assistant-thunderbird-update-server.service"

banner() {
  printf '\nCalDAV Assistant — Thunderbird Setup\n'
  printf '%s\n' '===================================='
}

run_full() {
  printf '\n[1/2] Deploy/repair lightweight Python update server\n'
  bash "$UPDATE_DEPLOY"
  printf '\n[2/2] Install/repair Native Host and build current XPI\n'
  bash "$HOST_INSTALL"
  printf '\nFull Thunderbird integration deployment: OK\n'
}

verify_update_server() {
  if [[ ! -f "$UPDATE_VERIFY" || ! -f "$CA_CERT" ]]; then
    echo "Update server is not deployed yet."
    return 1
  fi
  python3 "$UPDATE_VERIFY" --url "$UPDATE_URL" --ca "$CA_CERT"
}

verify_native_host() {
  if [[ ! -f "$HOST_LAUNCHER" ]]; then
    echo "Native Host is not installed yet."
    return 1
  fi
  python3 "$HOST_VERIFY" "$HOST_LAUNCHER"
}

show_status() {
  local version
  version="$(python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("'"$HERE"'/manifest.json").read_text())["version"])')"
  printf '\nExtension version: %s\n' "$version"
  printf 'Update URL:       %s\n' "$UPDATE_URL"
  printf 'Native Host:      %s\n' "$HOST_LAUNCHER"
  printf 'Log path:         %s\n' "$LOG_PATH"

  if systemctl --user is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Update server:    running"
  else
    echo "Update server:    not running"
  fi

  if [[ -f "$HOST_LAUNCHER" ]]; then
    echo "Native Host file: installed"
  else
    echo "Native Host file: missing"
  fi

  if [[ -r "$LOG_PATH" ]]; then
    echo "Log reachability: readable"
    printf 'Log size:         %s bytes\n' "$(wc -c <"$LOG_PATH")"
  else
    echo "Log reachability: NOT readable"
  fi
}

pause_for_user() {
  if [[ -t 0 ]]; then
    printf '\nPress Enter to return to the menu…'
    read -r _
  fi
}

if [[ "${1:-}" == "--all" ]]; then
  run_full
  exit 0
fi
if [[ "${1:-}" == "--status" ]]; then
  show_status
  exit 0
fi
if [[ "${1:-}" == "--verify" ]]; then
  verify_update_server
  verify_native_host
  exit 0
fi

if [[ "${1:-}" != "--terminal" && -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  if python3 -c 'import tkinter' >/dev/null 2>&1; then
    exec python3 "$HERE/setup_gui.py"
  fi
  echo "Desktop GUI is unavailable because Python tkinter is not installed; using terminal setup." >&2
fi

if [[ ! -t 0 ]]; then
  echo "Interactive setup needs a terminal. Running full deployment instead."
  run_full
  exit 0
fi

while true; do
  banner
  cat <<'EOF'

  1) Full install/update (recommended)
  2) Install/repair Native Host + build XPI
  3) Deploy/repair Python update server
  4) Verify update server
  5) Verify Native Host + log reachability
  6) Show status and paths
  0) Exit

EOF
  printf 'Choose [1]: '
  read -r choice
  choice="${choice:-1}"

  case "$choice" in
    1)
      run_full || true
      pause_for_user
      ;;
    2)
      bash "$HOST_INSTALL" || true
      pause_for_user
      ;;
    3)
      bash "$UPDATE_DEPLOY" || true
      pause_for_user
      ;;
    4)
      verify_update_server || true
      pause_for_user
      ;;
    5)
      verify_native_host || true
      pause_for_user
      ;;
    6)
      show_status
      pause_for_user
      ;;
    0)
      echo "Bye."
      exit 0
      ;;
    *)
      echo "Unknown choice: $choice"
      pause_for_user
      ;;
  esac
done
