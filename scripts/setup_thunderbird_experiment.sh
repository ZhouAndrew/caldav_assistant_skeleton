#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${ROOT}/venv/bin/python" ]]; then
  PYTHON="${ROOT}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "Python 3 was not found." >&2
  exit 1
fi

echo "== CalDAV Assistant Thunderbird experiment =="
echo "Python: ${PYTHON}"

"${PYTHON}" -m pip install -e "${ROOT}"
"${PYTHON}" -m caldav_assistant.internal.thunderbird.install
"${PYTHON}" "${ROOT}/scripts/build_thunderbird_xpi.py"

if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
DESKTOP="${DESKTOP:-${HOME}/Desktop}"
mkdir -p "${DESKTOP}"
TARGET="${DESKTOP}/caldav-assistant-thunderbird-experimental.xpi"
install -m 0644 "${ROOT}/dist/caldav-assistant-thunderbird.xpi" "${TARGET}"

echo
echo "Ready:"
echo "  ${TARGET}"
echo
echo "Thunderbird: Add-ons and Themes -> gear menu -> Install Add-on From File..."
echo "Select the XPI above, then open the CalDAV Assistant space."
