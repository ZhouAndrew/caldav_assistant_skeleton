#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("'"$HERE"'/manifest.json").read_text())["version"])')"
BUNDLE="$HERE/dist/caldav-assistant-thunderbird-experimental-$VERSION.zip"

if [[ ! -f "$BUNDLE" ]]; then
  echo "Bundle not found: $BUNDLE" >&2
  exit 1
fi

tmp="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp"
}
trap cleanup EXIT

home="$tmp/home"
bundle_dir="$tmp/bundle"
mkdir -p "$home/.mozilla/native-messaging-hosts" "$home/Desktop" "$bundle_dir"

unzip -q "$BUNDLE" -d "$bundle_dir"

host_name="local.caldav_assistant_experimental"
manifest="$home/.mozilla/native-messaging-hosts/$host_name.json"
cat >"$manifest" <<'EOF'
{
  "name": "local.caldav_assistant_experimental",
  "description": "Previous experimental host",
  "path": "/previous/host",
  "type": "stdio",
  "allowed_extensions": ["caldav-assistant-experimental@zhouandrew.local"]
}
EOF
cp "$manifest" "$tmp/original-manifest.json"

HOME="$home" XDG_DESKTOP_DIR="$home/Desktop" bash "$bundle_dir/install.sh"
cmp "$tmp/original-manifest.json"   "$home/.local/share/caldav-assistant-thunderbird-experimental/native-host-manifest.backup.json"

# A second install must keep the original backup, not replace it with our own host.
HOME="$home" XDG_DESKTOP_DIR="$home/Desktop" bash "$bundle_dir/install.sh"
cmp "$tmp/original-manifest.json"   "$home/.local/share/caldav-assistant-thunderbird-experimental/native-host-manifest.backup.json"

launcher="$home/.local/bin/caldav-assistant-thunderbird-host-experimental"
xpi="$home/Desktop/caldav-assistant-thunderbird-$VERSION.xpi"
[[ -x "$launcher" ]]
[[ -f "$xpi" ]]
grep -Fq '"path": "'"$launcher"'"' "$manifest"

HOME="$home" "$home/.local/share/caldav-assistant-thunderbird-experimental/venv/bin/python" - "$launcher" <<'PY'
from __future__ import annotations
import json
import struct
import subprocess
import sys

launcher = sys.argv[1]
proc = subprocess.Popen(
    [launcher],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
try:
    request = json.dumps({"command": "ping"}).encode("utf-8")
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(struct.pack("<I", len(request)) + request)
    proc.stdin.flush()
    size = struct.unpack("<I", proc.stdout.read(4))[0]
    response = json.loads(proc.stdout.read(size).decode("utf-8"))
    assert response["ok"] is True, response
    proc.stdin.close()
    assert proc.wait(timeout=5) == 0
finally:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)
PY

HOME="$home" bash "$bundle_dir/uninstall.sh"
cmp "$tmp/original-manifest.json" "$manifest"
[[ ! -e "$launcher" ]]
[[ ! -e "$home/.local/share/caldav-assistant-thunderbird-experimental" ]]

echo "Experimental bundle install/reinstall/native-host/uninstall selftest: OK"
