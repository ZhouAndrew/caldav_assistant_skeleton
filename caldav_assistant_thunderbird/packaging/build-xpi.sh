#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ADDON="$HERE/addon"
npm --prefix "$HERE" run build:core
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ADDON/manifest.json")"
OUT="${1:-$HERE/dist/caldav-assistant-thunderbird-$VERSION.xpi}"
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
        if p.is_file() and p.suffix in {".js", ".json", ".html", ".css", ".png", ".svg"}:
            info=zipfile.ZipInfo(p.as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,p.read_bytes())
with zipfile.ZipFile(out) as z:
    bad=z.testzip()
    if bad:
        raise SystemExit(f"Bad ZIP entry: {bad}")
print(out)
PY
)
