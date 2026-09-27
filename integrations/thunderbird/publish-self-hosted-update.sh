#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"
WWW_DIR="$STATE_DIR/www/experimental"
CONTAINER="caldav-assistant-thunderbird-update-server"
PORT="17443"
HOSTNAME="andrew.local"
UPDATE_URL="https://$HOSTNAME:$PORT/experimental/updates.json"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Standalone update server is not deployed." >&2
  echo "Run: bash $HERE/update-server/deploy.sh" >&2
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

manifest_json="$(curl --fail --silent --show-error "$UPDATE_URL")"
xpi_url="$(python3 -c 'import json, sys; data=json.load(sys.stdin); updates=next(iter(data["addons"].values()))["updates"]; print(updates[0]["update_link"])' <<<"$manifest_json")"
curl --fail --silent --show-error --head "$xpi_url" >/dev/null

echo "Standalone Thunderbird update published: OK"
echo "Update URL: $UPDATE_URL"
