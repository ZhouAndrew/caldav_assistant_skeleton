#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ADDON="$HERE/addon"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ADDON/manifest.json")"
OUT="${1:-$HERE/dist/caldav-assistant-experimental-$VERSION.xpi}"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
(
  cd "$ADDON"
  python3 - "$OUT" <<'PY'
from pathlib import Path
import sys, zipfile
root=Path(".")
out=Path(sys.argv[1]).resolve()
with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            z.write(p,p.as_posix())
with zipfile.ZipFile(out) as z:
    bad=z.testzip()
    if bad:
        raise SystemExit(f"Bad ZIP entry: {bad}")
print(out)
PY
)
