#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
npm --prefix "$HERE" run build:core
python3 "$HERE/packaging/build-xpi.py" "${1:-}"
