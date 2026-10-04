#!/usr/bin/env bash
set -euo pipefail

VERSION="${THUNDERBIRD_VERSION:-153.1.0esr}"
LOCALE="${THUNDERBIRD_LOCALE:-en-US}"
ROOT="${THUNDERBIRD_ROOT:-$PWD/.thunderbird-runtime}"
ARCHIVE="$ROOT/thunderbird-${VERSION}.tar.xz"
URL="https://download-origin.cdn.mozilla.net/pub/thunderbird/releases/${VERSION}/linux-x86_64/${LOCALE}/thunderbird-${VERSION}.tar.xz"

mkdir -p "$ROOT"

if [[ ! -x "$ROOT/thunderbird/thunderbird" ]]; then
  echo "Downloading Thunderbird ${VERSION} (${LOCALE}) from Mozilla..."
  curl --fail --location --retry 3 --retry-delay 2 "$URL" --output "$ARCHIVE"
  rm -rf "$ROOT/thunderbird"
  tar -xJf "$ARCHIVE" -C "$ROOT"
fi

TB="$ROOT/thunderbird/thunderbird"
"$TB" --version | tee "$ROOT/version.txt"

cat > "$ROOT/runtime.env" <<EOF
THUNDERBIRD_VERSION=$VERSION
THUNDERBIRD_BIN=$TB
THUNDERBIRD_ROOT=$ROOT
EOF

echo "Thunderbird runtime ready:"
echo "  version: $VERSION"
echo "  binary:  $TB"
echo "  env:     $ROOT/runtime.env"
