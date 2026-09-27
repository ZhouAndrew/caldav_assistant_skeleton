#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TB_DIR="$(cd "$HERE/.." && pwd)"
STATE_DIR="${CALDAV_ASSISTANT_TB_UPDATE_STATE:-$HOME/.local/share/caldav-assistant-thunderbird-update-server}"
WWW_DIR="$STATE_DIR/www"
TLS_DIR="$STATE_DIR/tls"
SERVER_PY="$STATE_DIR/server.py"
VERIFY_PY="$STATE_DIR/verify.py"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="caldav-assistant-thunderbird-update-server.service"
SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME"
PORT="17443"
HOSTNAME="andrew.local"
UPDATE_URL="https://$HOSTNAME:$PORT/experimental/updates.json"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

need python3
need openssl
need systemctl

PYTHON_BIN="$(command -v python3)"
mkdir -p "$WWW_DIR/experimental" "$TLS_DIR" "$SERVICE_DIR"

echo "== Build update feed =="
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

install -m 0644 "$HERE/server.py" "$SERVER_PY"
install -m 0644 "$HERE/verify.py" "$VERIFY_PY"

CA_KEY="$TLS_DIR/ca.key"
CA_CERT="$TLS_DIR/ca.crt"
SERVER_KEY="$TLS_DIR/server.key"
SERVER_CERT="$TLS_DIR/server.crt"
SERVER_CSR="$TLS_DIR/server.csr"
SERVER_EXT="$TLS_DIR/server.ext"

if [[ ! -s "$CA_KEY" || ! -s "$CA_CERT" ]]; then
  echo "== Create private update-server CA =="
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650     -keyout "$CA_KEY"     -out "$CA_CERT"     -subj "/CN=CalDAV Assistant Thunderbird Update CA"     -addext "basicConstraints=critical,CA:TRUE"     -addext "keyUsage=critical,keyCertSign,cRLSign"     >/dev/null 2>&1
  chmod 0600 "$CA_KEY"
  chmod 0644 "$CA_CERT"
fi

renew_server_cert=false
if [[ ! -s "$SERVER_KEY" || ! -s "$SERVER_CERT" ]]; then
  renew_server_cert=true
elif ! openssl x509 -checkend 2592000 -noout -in "$SERVER_CERT" >/dev/null 2>&1; then
  renew_server_cert=true
fi

if [[ "$renew_server_cert" == true ]]; then
  echo "== Issue HTTPS certificate for $HOSTNAME =="
  cat >"$SERVER_EXT" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$HOSTNAME,DNS:localhost,IP:127.0.0.1
EOF
  openssl req -new -newkey rsa:2048 -nodes     -keyout "$SERVER_KEY"     -out "$SERVER_CSR"     -subj "/CN=$HOSTNAME"     >/dev/null 2>&1
  openssl x509 -req     -in "$SERVER_CSR"     -CA "$CA_CERT"     -CAkey "$CA_KEY"     -CAcreateserial     -out "$SERVER_CERT"     -days 825     -sha256     -extfile "$SERVER_EXT"     >/dev/null 2>&1
  rm -f "$SERVER_CSR" "$SERVER_EXT" "$TLS_DIR/ca.srl"
  chmod 0600 "$SERVER_KEY"
  chmod 0644 "$SERVER_CERT"
fi

echo "== Install Thunderbird CA trust =="
if ! command -v certutil >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "Installing lightweight NSS certificate tool (libnss3-tools)..."
    sudo apt-get install -y libnss3-tools >/dev/null
  fi
fi
if ! command -v certutil >/dev/null 2>&1; then
  echo "certutil is required once to trust the private update CA in Thunderbird." >&2
  exit 1
fi

mapfile -t profiles < <(python3 - "$HOME" <<'PY'
from __future__ import annotations
import configparser
from pathlib import Path
import sys

home = Path(sys.argv[1])
seen: set[Path] = set()
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
  certutil -A -d "sql:$profile"     -n "CalDAV Assistant Update Server CA"     -t "C,,"     -i "$CA_CERT"
  imported=$((imported + 1))
done
if [[ "$imported" -eq 0 ]]; then
  echo "No Thunderbird NSS profile was found. Start Thunderbird once, then rerun this deployment." >&2
  exit 1
fi
echo "Thunderbird profiles trusted: $imported"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=CalDAV Assistant Thunderbird Update Server
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON_BIN "$SERVER_PY" --root "$WWW_DIR" --cert "$SERVER_CERT" --key "$SERVER_KEY" --bind 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF

echo "== Start lightweight Python HTTPS service =="
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"

for _ in $(seq 1 30); do
  if python3 "$VERIFY_PY" --url "$UPDATE_URL" --ca "$CA_CERT" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
python3 "$VERIFY_PY" --url "$UPDATE_URL" --ca "$CA_CERT"

echo
echo "Standalone Python Thunderbird update server: OK"
echo "Service: $SERVICE_NAME"
echo "Update URL: $UPDATE_URL"
echo "State: $STATE_DIR"
echo "Manifest: $WWW_DIR/experimental/updates.json"
echo "XPI: $WWW_DIR/experimental/$(basename "${xpis[0]}")"
