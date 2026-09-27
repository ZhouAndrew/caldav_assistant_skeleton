#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TB_DIR="$(cd "$HERE/.." && pwd)"
STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"
WWW_DIR="$STATE_DIR/www"
CADDY_DATA="$STATE_DIR/caddy-data"
CADDY_CONFIG="$STATE_DIR/caddy-config"
CADDYFILE="$STATE_DIR/Caddyfile"
CONTAINER="caldav-assistant-thunderbird-update-server"
IMAGE="${CALDAV_ASSISTANT_TB_UPDATE_IMAGE:-caddy:2-alpine}"
PORT="17443"
HOSTNAME="andrew.local"
UPDATE_URL="https://$HOSTNAME:$PORT/experimental/updates.json"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

need docker
need python3
need curl

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not usable by the current user." >&2
  exit 1
fi

mkdir -p "$WWW_DIR/experimental" "$CADDY_DATA" "$CADDY_CONFIG"
cp "$HERE/Caddyfile" "$CADDYFILE"

python3 "$TB_DIR/build-update-feed.py"
SOURCE="$TB_DIR/dist/update-site/experimental"
install -m 0644 "$SOURCE/updates.json" "$WWW_DIR/experimental/updates.json"

shopt -s nullglob
xpis=("$SOURCE"/caldav-assistant-thunderbird-*.xpi)
shopt -u nullglob
if [[ ${#xpis[@]} -ne 1 ]]; then
  echo "Expected exactly one generated XPI, found ${#xpis[@]}." >&2
  exit 1
fi
install -m 0644 "${xpis[0]}" "$WWW_DIR/experimental/$(basename "${xpis[0]}")"

docker pull "$IMAGE" >/dev/null
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -p "$PORT:$PORT" \
  -v "$WWW_DIR:/srv:ro" \
  -v "$CADDY_DATA:/data" \
  -v "$CADDY_CONFIG:/config" \
  -v "$CADDYFILE:/etc/caddy/Caddyfile:ro" \
  "$IMAGE" >/dev/null

echo "Waiting for standalone HTTPS server..."
for _ in $(seq 1 30); do
  if curl -kfsS --resolve "$HOSTNAME:$PORT:127.0.0.1" "https://$HOSTNAME:$PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -kfsS --resolve "$HOSTNAME:$PORT:127.0.0.1" "https://$HOSTNAME:$PORT/healthz" >/dev/null

ROOT_CA="$CADDY_DATA/caddy/pki/authorities/local/root.crt"
for _ in $(seq 1 20); do
  [[ -f "$ROOT_CA" ]] && break
  sleep 1
done
if [[ ! -f "$ROOT_CA" ]]; then
  echo "Caddy root CA was not created: $ROOT_CA" >&2
  exit 1
fi

# Trust the server CA in the OS store so ordinary tools can verify it.
if command -v update-ca-certificates >/dev/null 2>&1; then
  sudo install -m 0644 "$ROOT_CA" /usr/local/share/ca-certificates/caldav-assistant-thunderbird-update-server.crt
  sudo update-ca-certificates >/dev/null
fi

# Import directly into Thunderbird NSS profiles as well. This does not depend on
# Thunderbird inheriting the operating-system trust store.
if ! command -v certutil >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y libnss3-tools >/dev/null
  fi
fi

if command -v certutil >/dev/null 2>&1; then
  mapfile -t profiles < <(python3 - "$HOME" <<'PY'
from __future__ import annotations
import configparser
from pathlib import Path
import sys

home = Path(sys.argv[1])
seen = set()
for ini in (
    home / ".thunderbird" / "profiles.ini",
    home / ".local" / "share" / "thunderbird" / "profiles.ini",
):
    if not ini.is_file():
        continue
    parser = configparser.ConfigParser()
    parser.read(ini, encoding="utf-8")
    for section in parser.sections():
        if not section.startswith("Profile"):
            continue
        raw = parser.get(section, "Path", fallback="").strip()
        if not raw:
            continue
        path = Path(raw)
        if parser.getboolean(section, "IsRelative", fallback=True):
            path = ini.parent / path
        path = path.expanduser().resolve()
        if path.is_dir() and path not in seen:
            seen.add(path)
            print(path)
PY
)
  imported=0
  for profile in "${profiles[@]:-}"; do
    [[ -f "$profile/cert9.db" ]] || continue
    certutil -D -d "sql:$profile" -n "CalDAV Assistant Update Server CA" >/dev/null 2>&1 || true
    certutil -A -d "sql:$profile" \
      -n "CalDAV Assistant Update Server CA" \
      -t "C,," \
      -i "$ROOT_CA"
    imported=$((imported + 1))
  done
  echo "Thunderbird profiles trusted: $imported"
else
  echo "WARNING: certutil is unavailable; Thunderbird CA trust was not installed." >&2
fi

echo
echo "Verifying standalone update service..."
manifest_json="$(curl --fail --silent --show-error "$UPDATE_URL")"
xpi_url="$(python3 -c 'import json, sys; data=json.load(sys.stdin); updates=next(iter(data["addons"].values()))["updates"]; print(updates[0]["update_link"])' <<<"$manifest_json")"
curl --fail --silent --show-error --head "$xpi_url" >/dev/null

echo
echo "Standalone Thunderbird update server: OK"
echo "Container: $CONTAINER"
echo "Update URL: $UPDATE_URL"
echo "State: $STATE_DIR"
echo "Manifest: $WWW_DIR/experimental/updates.json"
echo "XPI: $WWW_DIR/experimental/$(basename "${xpis[0]}")"
