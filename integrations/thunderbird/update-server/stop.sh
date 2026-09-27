#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"
CONTAINER="caldav-assistant-thunderbird-update-server"

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

echo "Standalone Thunderbird update server stopped."
echo "State retained at: $STATE_DIR"
echo "The locally trusted CA is intentionally retained so a later reinstall uses the same trust relationship."
