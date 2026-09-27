#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"
WWW_DIR="$STATE_DIR/www/experimental"
CA_CERT="$STATE_DIR/tls/ca.crt"
VERIFY_PY="$STATE_DIR/verify.py"
SERVICE_NAME="caldav-assistant-thunderbird-update-server.service"
PORT="17443"
HOSTNAME="andrew.local"
UPDATE_URL="https://$HOSTNAME:$PORT/experimental/updates.json"

if ! systemctl --user is-active --quiet "$SERVICE_NAME"; then
  echo "Standalone Python update server is not running." >&2
  echo "Run: bash $HERE/update-server/deploy.sh" >&2
  exit 1
fi
if [[ ! -f "$CA_CERT" || ! -f "$VERIFY_PY" ]]; then
  echo "Standalone update server state is incomplete; redeploy it." >&2
  exit 1
fi

python3 "$HERE/build-update-feed.py"
SOURCE="$HERE/dist/update-site/experimental"
mkdir -p "$WWW_DIR"
install -m 0644 "$SOURCE/updates.json" "$WWW_DIR/updates.json"

shopt -s nullglob
xpis=("$SOURCE"/caldav-assistant-thunderbird-*.xpi)
shopt -u nullglob
if [[ ${#xpis[@]} -ne 1 ]]; then
  echo "Expected exactly one generated XPI, found ${#xpis[@]}." >&2
  exit 1
fi
install -m 0644 "${xpis[0]}" "$WWW_DIR/$(basename "${xpis[0]}")"

python3 "$VERIFY_PY" --url "$UPDATE_URL" --ca "$CA_CERT"

echo "Standalone Thunderbird update published: OK"
echo "Update URL: $UPDATE_URL"
