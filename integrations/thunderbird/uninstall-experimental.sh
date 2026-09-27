#!/usr/bin/env bash
set -euo pipefail

HOST_NAME="local.caldav_assistant"
BASE_DIR="$HOME/.local/share/caldav-assistant-thunderbird-experimental"
BIN="$HOME/.local/bin/caldav-assistant-thunderbird-host-experimental"
MANIFEST="$HOME/.mozilla/native-messaging-hosts/$HOST_NAME.json"

if [[ -f "$BASE_DIR/native-host-manifest.backup.json" ]]; then
  mkdir -p "$(dirname "$MANIFEST")"
  cp -f "$BASE_DIR/native-host-manifest.backup.json" "$MANIFEST"
  echo "Restored previous native-host manifest."
else
  rm -f "$MANIFEST"
fi

rm -f "$BIN"
rm -rf "$BASE_DIR"

echo "Experimental native host removed."
echo "The Thunderbird XPI itself is not removed automatically; remove it from Add-ons and Themes."
echo "Production CalDAV Assistant data and installation were not touched."
