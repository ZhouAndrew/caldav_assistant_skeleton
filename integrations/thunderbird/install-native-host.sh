#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXT_ID="caldav-assistant@zhouandrew.local"
HOST_NAME="local.caldav_assistant"
LIB_DIR="$HOME/.local/lib/caldav-assistant-thunderbird"
BIN_DIR="$HOME/.local/bin"
MANIFEST_DIR="$HOME/.mozilla/native-messaging-hosts"

assistant_bin="$(command -v caldav-assistant || true)"
if [[ -z "$assistant_bin" ]]; then
  echo "caldav-assistant is not installed on PATH." >&2
  exit 1
fi

python_bin="$(head -n 1 "$assistant_bin" | sed 's/^#!//')"
if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi

mkdir -p "$LIB_DIR" "$BIN_DIR" "$MANIFEST_DIR"
cp "$ROOT/integrations/thunderbird/native_host.py" "$LIB_DIR/native_host.py"
chmod 700 "$LIB_DIR/native_host.py"

launcher="$BIN_DIR/caldav-assistant-thunderbird-host"
cat >"$launcher" <<EOF
#!/usr/bin/env bash
exec "$python_bin" "$LIB_DIR/native_host.py"
EOF
chmod 700 "$launcher"

manifest="$MANIFEST_DIR/$HOST_NAME.json"
cat >"$manifest" <<EOF
{
  "name": "$HOST_NAME",
  "description": "CalDAV Assistant native host for Thunderbird",
  "path": "$launcher",
  "type": "stdio",
  "allowed_extensions": ["$EXT_ID"]
}
EOF

echo "Native host installed:"
echo "  $manifest"
echo "  $launcher"
