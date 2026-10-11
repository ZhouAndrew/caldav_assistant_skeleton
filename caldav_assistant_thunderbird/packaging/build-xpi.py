"""Unique package identity; an existing identity can only be reused from an exact reference XPI."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, subprocess, sys, uuid, zipfile

root=Path(__file__).resolve().parent.parent
addon=root/'addon'
version=json.loads((addon/'manifest.json').read_text())['version']

reference_text=os.environ.get('CALDAV_REPRODUCE_FROM_XPI','').strip()
reference=Path(reference_text).expanduser().resolve() if reference_text else None
reference_bytes=None
reference_info=None
if reference:
 if not reference.is_file():
  raise SystemExit(f'Reproduction reference XPI not found: {reference}')
 reference_bytes=reference.read_bytes()
 try:
  with zipfile.ZipFile(reference) as z:
   if z.testzip(): raise SystemExit('Reproduction reference XPI is corrupt')
   reference_info=json.loads(z.read('build-info.json'))
 except (KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
  raise SystemExit(f'Invalid reproduction reference XPI: {error}')
 build_id=str(reference_info.get('buildId') or '')
 if not build_id:
  raise SystemExit('Reproduction reference XPI has no buildId')
else:
 build_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex

if not all(c.isalnum() or c in '-_' for c in build_id):
 raise SystemExit('Invalid build ID')

# Published release XPIs are the trusted build-ID registry. A caller cannot
# redefine an already published ID by pointing reproduction mode at another file.
known_artifact=None
releases=root/'releases'
if releases.is_dir():
 for candidate in sorted(releases.rglob('*.xpi')):
  try:
   with zipfile.ZipFile(candidate) as z:
    candidate_info=json.loads(z.read('build-info.json'))
  except (KeyError, json.JSONDecodeError, zipfile.BadZipFile):
   continue
  if str(candidate_info.get('buildId') or '') == build_id:
   known_artifact=candidate.resolve()
   break
if known_artifact:
 known_bytes=known_artifact.read_bytes()
 if reference_bytes is None:
  raise SystemExit(f'Build ID {build_id} already belongs to {known_artifact}')
 if reference_bytes != known_bytes:
  raise SystemExit(f'Reproduction reference does not match published artifact for build ID {build_id}')
 reference_bytes=known_bytes
 with zipfile.ZipFile(known_artifact) as z:
  reference_info=json.loads(z.read('build-info.json'))

out=Path(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1] else root/'dist'/f'caldav-assistant-thunderbird-{version}-{build_id}.xpi'
if build_id not in out.name:
 out=out.with_name(out.stem+'-'+build_id+out.suffix)
out=out.resolve();out.parent.mkdir(parents=True,exist_ok=True)
if out.exists(): raise SystemExit('Refusing to overwrite a packaged build')

files={p.relative_to(addon).as_posix():p.read_bytes() for p in sorted(addon.rglob('*')) if p.is_file() and p.suffix in {'.js','.json','.html','.css','.png','.svg'}}
files.pop('build-info.json',None)
source_hash=hashlib.sha256(b''.join(name.encode()+b'\0'+data for name,data in sorted(files.items()))).hexdigest()
commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()

# Provenance must describe exactly the bytes that can enter this XPI. Compare
# the current packaged file set with HEAD itself instead of relying on git
# status, which can include excluded files and omit ignored package inputs.
repo_prefix=subprocess.check_output(
 ['git','-C',str(root),'rev-parse','--show-prefix'],
 text=True,
).strip()
addon_repo_prefix=repo_prefix+'addon/'
addon_local_prefix='addon/'
tracked_names={
 path[len(addon_local_prefix):]
 for path in subprocess.check_output(
  ['git','-C',str(root),'ls-tree','-r','--name-only','HEAD','--',addon_local_prefix],
  text=True,
 ).splitlines()
 if path.startswith(addon_local_prefix) and Path(path).suffix in {'.js','.json','.html','.css','.png','.svg'}
}
current_names=set(files)
source_dirty=current_names != tracked_names
if not source_dirty:
 for name,data in files.items():
  head_data=subprocess.check_output(
   ['git','-C',str(root),'show',f'HEAD:{addon_repo_prefix}{name}']
  )
  if data != head_data:
   source_dirty=True
   break

if reference:
 if source_dirty:
  raise SystemExit('Refusing reproduction from a dirty source tree')
 if str(reference_info.get('version') or '') != version:
  raise SystemExit(f'Reproduction version mismatch: reference {reference_info.get("version")}, source {version}')
 if str(reference_info.get('sourceDigest') or '') != source_hash:
  raise SystemExit('Reproduction source digest does not match the reference XPI')
 if str(reference_info.get('sourceCommit') or '') != commit:
  raise SystemExit('Reproduction source commit does not match the reference XPI')

info={'buildId':build_id,'version':version,'sourceCommit':commit,'sourceDigest':source_hash,'sourceDirty':source_dirty}
files['build-info.json']=(json.dumps(info,indent=2)+'\n').encode()
with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for name,data in sorted(files.items()):
  entry=zipfile.ZipInfo(name,(2026,1,1,0,0,0))
  entry.compress_type=zipfile.ZIP_DEFLATED
  entry.external_attr=0o100644<<16
  z.writestr(entry,data)
with zipfile.ZipFile(out) as z:
 if z.testzip():
  out.unlink(missing_ok=True)
  raise SystemExit('Corrupt package')

if reference_bytes is not None and out.read_bytes()!=reference_bytes:
 out.unlink(missing_ok=True)
 raise SystemExit('Reproduction archive differs from the reference XPI')

print(out)
