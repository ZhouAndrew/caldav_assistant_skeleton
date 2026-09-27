#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="/var/www/html/caldav-assistant/thunderbird/experimental"
PUBLISH_ROOT="${CALDAV_ASSISTANT_TB_UPDATE_ROOT:-$DEFAULT_ROOT}"
UPDATE_URL="https://andrew.local/caldav-assistant/thunderbird/experimental/updates.json"

python3 "$HERE/build-update-feed.py"
SOURCE="$HERE/dist/update-site/experimental"

install_files() {
  install -d -m 0755 "$PUBLISH_ROOT"
  install -m 0644 "$SOURCE/updates.json" "$PUBLISH_ROOT/updates.json"
  shopt -s nullglob
  local xpis=("$SOURCE"/caldav-assistant-thunderbird-*.xpi)
  shopt -u nullglob
  if [[ ${#xpis[@]} -ne 1 ]]; then
    echo "Expected exactly one XPI in $SOURCE, found ${#xpis[@]}." >&2
    exit 1
  fi
  install -m 0644 "${xpis[0]}" "$PUBLISH_ROOT/$(basename "${xpis[0]}")"
}

if [[ -d "$PUBLISH_ROOT" && -w "$PUBLISH_ROOT" ]] || [[ ! -e "$PUBLISH_ROOT" && -w "$(dirname "$PUBLISH_ROOT")" ]]; then
  install_files
else
  sudo bash -c '
    set -euo pipefail
    root="$1"
    source="$2"
    install -d -m 0755 "$root"
    install -m 0644 "$source/updates.json" "$root/updates.json"
    xpis=("$source"/caldav-assistant-thunderbird-*.xpi)
    if [[ ${#xpis[@]} -ne 1 ]]; then
      echo "Expected exactly one XPI in $source, found ${#xpis[@]}." >&2
      exit 1
    fi
    install -m 0644 "${xpis[0]}" "$root/$(basename "${xpis[0]}")"
  ' bash "$PUBLISH_ROOT" "$SOURCE"
fi

echo
echo "Published Thunderbird experimental update feed:"
echo "  $PUBLISH_ROOT"
echo "Expected URL:"
echo "  $UPDATE_URL"
echo
echo "Verifying HTTPS endpoint..."
curl --fail --silent --show-error "$UPDATE_URL" >/dev/null
echo "HTTPS update manifest: OK"
