import json, os, shutil, subprocess, tempfile, zipfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
 tmp=Path(tmp)

 original=Path(subprocess.check_output(
  ['python3','packaging/build-xpi.py',str(tmp/'original.xpi')],
  text=True,
 ).strip())
 subprocess.run(['python3','tests/check-xpi.py',str(original)],check=True)
 with zipfile.ZipFile(original) as z:
  info=json.loads(z.read('build-info.json'))
  assert all(i.date_time==(2026,1,1,0,0,0) for i in z.infolist())

 reproduce_env={**os.environ,'CALDAV_REPRODUCE_FROM_XPI':str(original)}
 replicas=[tmp/'replica-a.xpi',tmp/'replica-b.xpi']
 for path in replicas:
  subprocess.run(['bash','packaging/build-xpi.sh',str(path)],check=True,env=reproduce_env)
  subprocess.run(['python3','tests/check-xpi.py',str(path)],check=True)
  assert path.read_bytes()==original.read_bytes(),'reference reproduction changed archive bytes'

 accepted=Path('releases/0.4.2/caldav-assistant-thunderbird-0.4.2-20261005T090627Z-bb8c684b828b46b3a4cdba3bdd62a91e.xpi')
 assert accepted.is_file(),'accepted 0.4.2 release artifact missing'
 with zipfile.ZipFile(accepted) as z:
  accepted_info=json.loads(z.read('build-info.json'))
  assert accepted_info['buildId']=='20261005T090627Z-bb8c684b828b46b3a4cdba3bdd62a91e'

 # Current 0.4.3 source must never be repackaged under the published 0.4.2 ID.
 old_id_attempt=subprocess.run(
  ['python3','packaging/build-xpi.py',str(tmp/'old-id.xpi')],
  env={**os.environ,'CALDAV_REPRODUCE_FROM_XPI':str(accepted.resolve())},
  capture_output=True,
  text=True,
 )
 assert old_id_attempt.returncode != 0,'changed source reused the accepted 0.4.2 build ID'
 assert not (tmp/'old-id.xpi').exists(),'failed old-ID reproduction left an artifact behind'

 # A caller cannot substitute another file that merely claims a published build ID.
 tampered=tmp/'tampered-reference.xpi'
 shutil.copyfile(accepted,tampered)
 with zipfile.ZipFile(tampered,'a',compression=zipfile.ZIP_DEFLATED) as z:
  z.writestr('tamper.txt',b'not the published artifact')
 tampered_attempt=subprocess.run(
  ['python3','packaging/build-xpi.py',str(tmp/'tampered-output.xpi')],
  env={**os.environ,'CALDAV_REPRODUCE_FROM_XPI':str(tampered)},
  capture_output=True,
  text=True,
 )
 assert tampered_attempt.returncode != 0,'forged reference overrode the published build-ID registry'
 assert 'does not match published artifact' in (tampered_attempt.stdout+tampered_attempt.stderr)

 unique=[]
 for index in range(2):
  result=subprocess.check_output(
   ['python3','packaging/build-xpi.py',str(tmp/f'unique-{index}.xpi')],
   text=True,
  ).strip()
  with zipfile.ZipFile(result) as z:
   unique.append(json.loads(z.read('build-info.json'))['buildId'])
 assert unique[0]!=unique[1]

print('Unique build IDs and reference-bound exact-byte reproduction: PASS')
