import json, os, subprocess, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
 paths=[Path(tmp)/name for name in ('a.xpi','b.xpi')]
 env={**os.environ,'CALDAV_REPRODUCE_BUILD_ID':'reproduction-test-only'}
 for path in paths:
  subprocess.run(['bash','packaging/build-xpi.sh',str(path)],check=True,env=env)
  subprocess.run(['python3','tests/check-xpi.py',str(path)],check=True)
 assert paths[0].read_bytes()==paths[1].read_bytes(),'non-reproducible XPI'
 with zipfile.ZipFile(paths[0]) as z:
  assert json.loads(z.read('build-info.json'))['buildId']=='reproduction-test-only'
  assert all(i.date_time==(2026,1,1,0,0,0) for i in z.infolist())
 unique=[]
 for _ in range(2):
  result=subprocess.check_output(['python3','packaging/build-xpi.py',str(Path(tmp)/'unique.xpi')],text=True).strip()
  with zipfile.ZipFile(result) as z: unique.append(json.loads(z.read('build-info.json'))['buildId'])
 assert unique[0]!=unique[1]
print('Unique build IDs and explicit byte reproduction: PASS')
