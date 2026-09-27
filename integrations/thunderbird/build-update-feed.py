#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit


HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
SITE = DIST / "update-site" / "experimental"


def main() -> int:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    gecko = manifest["browser_specific_settings"]["gecko"]
    addon_id = str(gecko["id"])
    minimum = str(gecko["strict_min_version"])
    update_url = str(gecko["update_url"])

    parsed = urlsplit(update_url)
    if parsed.scheme != "https":
        raise RuntimeError("Thunderbird update_url must use HTTPS")
    if not parsed.netloc:
        raise RuntimeError("Thunderbird update_url must have a host")

    subprocess.run([sys.executable, str(HERE / "build-xpi.py")], check=True)
    xpi = DIST / f"caldav-assistant-thunderbird-{version}.xpi"
    if not xpi.is_file():
        raise RuntimeError(f"XPI was not built: {xpi}")

    SITE.mkdir(parents=True, exist_ok=True)
    # The update site represents one current release. Remove stale generated
    # XPIs so repeated local builds cannot make deployment ambiguous.
    for stale in SITE.glob("caldav-assistant-thunderbird-*.xpi"):
        if stale.name != xpi.name:
            stale.unlink()
    published_xpi = SITE / xpi.name
    shutil.copy2(xpi, published_xpi)

    digest = hashlib.sha256(published_xpi.read_bytes()).hexdigest()
    base_path = parsed.path.rsplit("/", 1)[0].rstrip("/") + "/"
    xpi_url = urlunsplit(
        (parsed.scheme, parsed.netloc, base_path + published_xpi.name, "", "")
    )

    update_manifest = {
        "addons": {
            addon_id: {
                "updates": [
                    {
                        "version": version,
                        "update_link": xpi_url,
                        "update_hash": f"sha256:{digest}",
                        "applications": {
                            "gecko": {
                                "strict_min_version": minimum,
                            }
                        },
                    }
                ]
            }
        }
    }

    target = SITE / "updates.json"
    target.write_text(
        json.dumps(update_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(target)
    print(published_xpi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
