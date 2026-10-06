"""Unique package identity; explicit identity is only for verified byte reproduction."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, subprocess, sys, uuid, zipfile

root=Path(__file__).resolve().parent.parent
addon=root/'addon'
version=json.loads((addon/'manifest.json').read_text())['version']
reproduce_build_id=os.environ.get('CALDAV_REPRODUCE_BUILD_ID')
build_id=reproduce_build_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex
if not all(c.isalnum() or c in '-_' for c in build_id): raise SystemExit('Invalid build ID')

out=Path(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1] else root/'dist'/f'caldav-assistant-thunderbird-{version}-{build_id}.xpi'
if not reproduce_build_id and build_id not in out.name:
 out=out.with_name(out.stem+'-'+build_id+out.suffix)
out=out.resolve();out.parent.mkdir(parents=True,exist_ok=True)
if out.exists(): raise SystemExit('Refusing to overwrite a packaged build')

files={p.relative_to(addon).as_posix():p.read_bytes() for p in sorted(addon.rglob('*')) if p.is_file() and p.suffix in {'.js','.json','.html','.css','.png','.svg'}}
files.pop('build-info.json',None)
source_hash=hashlib.sha256(b''.join(name.encode()+b'\0'+data for name,data in sorted(files.items()))).hexdigest()
commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
source_dirty=bool(subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True))

if reproduce_build_id:
 expected_digest=os.environ.get('CALDAV_REPRODUCE_SOURCE_DIGEST','').strip()
 expected_commit=os.environ.get('CALDAV_REPRODUCE_SOURCE_COMMIT','').strip()
 if not expected_digest or not expected_commit:
  raise SystemExit('Reproduction mode requires CALDAV_REPRODUCE_SOURCE_DIGEST and CALDAV_REPRODUCE_SOURCE_COMMIT')
 if source_dirty:
  raise SystemExit('Refusing reproduction from a dirty source tree')
 if source_hash != expected_digest:
  raise SystemExit(f'Reproduction source digest mismatch: expected {expected_digest}, got {source_hash}')
 if commit != expected_commit:
  raise SystemExit(f'Reproduction source commit mismatch: expected {expected_commit}, got {commit}')

info={'buildId':build_id,'version':version,'sourceCommit':commit,'sourceDigest':source_hash,'sourceDirty':source_dirty}
files['build-info.json']=(json.dumps(info,indent=2)+'\n').encode()
with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for name,data in sorted(files.items()):
  entry=zipfile.ZipInfo(name,(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16;z.writestr(entry,data)
with zipfile.ZipFile(out) as z:
 if z.testzip():raise SystemExit('Corrupt package')
print(out)
