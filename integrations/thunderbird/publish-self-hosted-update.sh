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

XPI_NAME="$(python3 - "$SOURCE/updates.json" <<'PY'
from __future__ import annotations
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

manifest = Path(sys.argv[1])
data = json.loads(manifest.read_text(encoding="utf-8"))
updates = next(iter(data["addons"].values()))["updates"]
if len(updates) != 1:
    raise SystemExit(f"Expected exactly one current update entry, found {len(updates)}")
name = Path(urlsplit(str(updates[0]["update_link"])).path).name
if not name.endswith(".xpi"):
    raise SystemExit(f"Update link does not point to an XPI: {name!r}")
print(name)
PY
)"
XPI_PATH="$SOURCE/$XPI_NAME"
if [[ ! -f "$XPI_PATH" ]]; then
  echo "Update manifest references missing XPI: $XPI_PATH" >&2
  exit 1
fi
install -m 0644 "$XPI_PATH" "$WWW_DIR/$XPI_NAME"

python3 "$VERIFY_PY" --url "$UPDATE_URL" --ca "$CA_CERT"

echo "Standalone Thunderbird update published: OK"
echo "Update URL: $UPDATE_URL"
