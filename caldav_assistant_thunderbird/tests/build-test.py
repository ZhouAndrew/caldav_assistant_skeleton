import json, os, subprocess, tempfile, zipfile
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

 reproduce_env={
  **os.environ,
  'CALDAV_REPRODUCE_BUILD_ID':info['buildId'],
  'CALDAV_REPRODUCE_SOURCE_DIGEST':info['sourceDigest'],
  'CALDAV_REPRODUCE_SOURCE_COMMIT':info['sourceCommit'],
 }
 replicas=[tmp/'replica-a.xpi',tmp/'replica-b.xpi']
 for path in replicas:
  subprocess.run(['bash','packaging/build-xpi.sh',str(path)],check=True,env=reproduce_env)
  subprocess.run(['python3','tests/check-xpi.py',str(path)],check=True)
  assert path.read_bytes()==original.read_bytes(),'verified reproduction changed archive bytes'

 missing_guard=subprocess.run(
  ['python3','packaging/build-xpi.py',str(tmp/'unguarded.xpi')],
  env={**os.environ,'CALDAV_REPRODUCE_BUILD_ID':info['buildId']},
  capture_output=True,
  text=True,
 )
 assert missing_guard.returncode != 0,'reproduction accepted a build ID without source guards'

 wrong_digest=subprocess.run(
  ['python3','packaging/build-xpi.py',str(tmp/'wrong-digest.xpi')],
  env={**reproduce_env,'CALDAV_REPRODUCE_SOURCE_DIGEST':'0'*64},
  capture_output=True,
  text=True,
 )
 assert wrong_digest.returncode != 0,'reproduction accepted the wrong source digest'

 unique=[]
 for index in range(2):
  result=subprocess.check_output(
   ['python3','packaging/build-xpi.py',str(tmp/f'unique-{index}.xpi')],
   text=True,
  ).strip()
  with zipfile.ZipFile(result) as z:
   unique.append(json.loads(z.read('build-info.json'))['buildId'])
 assert unique[0]!=unique[1]

print('Unique build IDs and guarded exact-byte reproduction: PASS')
