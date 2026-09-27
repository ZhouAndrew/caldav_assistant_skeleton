#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXT_ID="caldav-assistant-experimental@zhouandrew.local"
HOST_NAME="local.caldav_assistant_experimental"
BASE_DIR="$HOME/.local/share/caldav-assistant-thunderbird-experimental"
VENV_DIR="$BASE_DIR/venv"
LIB_DIR="$BASE_DIR/host"
BIN_DIR="$HOME/.local/bin"
MANIFEST_DIR="$HOME/.mozilla/native-messaging-hosts"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
LOG_DIR="$HOME/.local/state/caldav-assistant/thunderbird"
LOG_PATH="$LOG_DIR/native-host.log"
python3_bin="$(command -v python3 || true)"
if [[ -z "$python3_bin" ]]; then
  echo "python3 is required." >&2
  exit 1
fi

VERSION="$("$python3_bin" -c 'import json, pathlib; print(json.loads(pathlib.Path("'"$ROOT"'/integrations/thunderbird/manifest.json").read_text())["version"])')"
XPI_NAME="caldav-assistant-thunderbird-$VERSION.xpi"

mkdir -p "$BASE_DIR" "$LIB_DIR" "$BIN_DIR" "$MANIFEST_DIR" "$DESKTOP_DIR" "$LOG_DIR"
touch "$LOG_PATH"
chmod 600 "$LOG_PATH"
ln -sfn "$LOG_PATH" "$BASE_DIR/native-host.log"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$python3_bin" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --upgrade "$ROOT"

cp "$ROOT/integrations/thunderbird/native_host.py" "$LIB_DIR/native_host.py"
chmod 700 "$LIB_DIR/native_host.py"

launcher="$BIN_DIR/caldav-assistant-thunderbird-host-experimental"
cat >"$launcher" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" "$LIB_DIR/native_host.py"
EOF
chmod 700 "$launcher"

manifest="$MANIFEST_DIR/$HOST_NAME.json"
backup="$BASE_DIR/native-host-manifest.backup.json"
if [[ -f "$manifest" && ! -f "$backup" ]]; then
  if ! grep -Fq "\"path\": \"$launcher\"" "$manifest"; then
    cp -a "$manifest" "$backup"
  fi
fi
cat >"$manifest" <<EOF
{
  "name": "$HOST_NAME",
  "description": "CalDAV Assistant experimental native host for Thunderbird",
  "path": "$launcher",
  "type": "stdio",
  "allowed_extensions": ["$EXT_ID"]
}
EOF

"$VENV_DIR/bin/python" "$ROOT/integrations/thunderbird/build-xpi.py"
cp -f "$ROOT/integrations/thunderbird/dist/$XPI_NAME" "$DESKTOP_DIR/$XPI_NAME"

"$VENV_DIR/bin/python" -m py_compile "$LIB_DIR/native_host.py"
"$VENV_DIR/bin/python" - <<'PY'
from caldav_assistant.internal.bootstrap import build_service_application
assert callable(build_service_application)
print("Experimental Core import: OK")
PY
"$VENV_DIR/bin/python" "$ROOT/integrations/thunderbird/verify-installed-native-host.py" "$launcher"

echo
echo "Experimental Thunderbird integration installed."
echo "Production caldav-assistant was not replaced."
echo
echo "Native host:"
echo "  $manifest"
echo "  $launcher"
echo "Native Host log:"
echo "  $LOG_PATH"
echo "  $BASE_DIR/native-host.log -> $LOG_PATH"
echo
echo "XPI ready on Desktop:"
echo "  $DESKTOP_DIR/$XPI_NAME"
echo
echo "Next: Thunderbird -> Add-ons and Themes -> gear -> Install Add-on From File..."
