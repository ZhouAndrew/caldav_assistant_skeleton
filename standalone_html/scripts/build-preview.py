"""Package a uniquely identified static preview with sources and license notices."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import uuid
import zipfile

root = Path(__file__).resolve().parents[1]
build = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
out = root / 'dist'
out.mkdir(exist_ok=True)
artifact = out / f'caldav-assistant-html-preview-{build}.zip'
source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
with zipfile.ZipFile(artifact, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in root.rglob('*'):
        if not path.is_file() or 'dist' in path.relative_to(root).parts or 'node_modules' in path.relative_to(root).parts:
            continue
        archive.write(path, 'standalone_html/' + str(path.relative_to(root)))
    archive.write(root / 'node_modules/ical.js/dist/ical.js', 'standalone_html/node_modules/ical.js/dist/ical.js')
    archive.write(root.parent / 'LICENSE', 'LICENSE')
    archive.write(root.parent / 'caldav_assistant_thunderbird/src/core.ts', 'caldav_assistant_thunderbird/src/core.ts')
    archive.writestr('BUILD.json', json.dumps({'buildId': build, 'sourceCommit': source, 'acceptance': 'service-tested; browser-pending'}, indent=2))
    archive.writestr('START.txt', 'Preview only; full plugin pages and restart recovery acceptance are incomplete.\n\nFrom standalone_html, run: python3 -m http.server 8765 --bind 127.0.0.1\nOpen http://127.0.0.1:8765/selector.html\nCalDAV must allow this origin, methods and ETag via CORS; browser certificate trust applies.\nNo internet or npm is needed to run the compiled preview.\nRebuild from sources: cd standalone_html && npm ci && npm test\nCredentials stay in memory. currentWorkId alone is stored per server origin and username.\nDo not use production data before browser and recovery acceptance.\n')
checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
(artifact.with_suffix('.zip.sha256')).write_text(checksum + '  ' + artifact.name + '\n')
print(artifact)
