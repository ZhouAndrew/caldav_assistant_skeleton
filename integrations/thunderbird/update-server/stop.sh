#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="caldav-assistant-thunderbird-update-server.service"
STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"

systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true

echo "Standalone Python Thunderbird update server stopped."
echo "State retained at: $STATE_DIR"
echo "The private CA is retained so a later redeploy keeps the same trust relationship."
