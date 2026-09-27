#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_ID="caldav-assistant-experimental@zhouandrew.local"
HOST_NAME="local.caldav_assistant_experimental"
BASE_DIR="$HOME/.local/share/caldav-assistant-thunderbird-experimental"
VENV_DIR="$BASE_DIR/venv"
LIB_DIR="$BASE_DIR/host"
BIN_DIR="$HOME/.local/bin"
MANIFEST_DIR="$HOME/.mozilla/native-messaging-hosts"
XPI_NAME="caldav-assistant-thunderbird-0.1.0.xpi"

desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [[ -z "$desktop_dir" ]]; then
  desktop_dir="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
fi

python3_bin="$(command -v python3 || true)"
if [[ -z "$python3_bin" ]]; then
  echo "python3 is required." >&2
  exit 1
fi

shopt -s nullglob
wheels=("$ROOT"/caldav_assistant-*.whl)
shopt -u nullglob
if [[ ${#wheels[@]} -ne 1 ]]; then
  echo "Expected exactly one caldav_assistant wheel beside this installer." >&2
  exit 1
fi
if [[ ! -f "$ROOT/$XPI_NAME" || ! -f "$ROOT/native_host.py" ]]; then
  echo "Experimental bundle is incomplete." >&2
  exit 1
fi

mkdir -p "$BASE_DIR" "$LIB_DIR" "$BIN_DIR" "$MANIFEST_DIR" "$desktop_dir"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$python3_bin" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --upgrade "${wheels[0]}"

cp -f "$ROOT/native_host.py" "$LIB_DIR/native_host.py"
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

cp -f "$ROOT/$XPI_NAME" "$desktop_dir/$XPI_NAME"
"$VENV_DIR/bin/python" -m py_compile "$LIB_DIR/native_host.py"
"$VENV_DIR/bin/python" - <<'PY'
from caldav_assistant.internal.bootstrap import build_service_application
assert callable(build_service_application)
print("Experimental Core import: OK")
PY

echo
echo "Experimental Thunderbird integration installed side-by-side."
echo "Production caldav-assistant was not replaced."
echo
echo "XPI:"
echo "  $desktop_dir/$XPI_NAME"
echo
echo "Install it in Thunderbird:"
echo "  Add-ons and Themes -> gear -> Install Add-on From File..."
