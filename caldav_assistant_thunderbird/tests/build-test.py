"""Two independent builds must produce exactly the same production bytes."""
import hashlib, subprocess, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
 paths=[Path(tmp)/name for name in ('a.xpi','b.xpi')]
 for path in paths:
  subprocess.run(['bash','packaging/build-xpi.sh',str(path)],check=True)
  subprocess.run(['python3','tests/check-xpi.py',str(path)],check=True)
 assert paths[0].read_bytes()==paths[1].read_bytes(),'non-reproducible XPI'
 with zipfile.ZipFile(paths[0]) as z:
  assert all(not n.endswith('.md') for n in z.namelist())
  assert all(i.date_time==(2026,1,1,0,0,0) for i in z.infolist())
print('Reproducible production build: PASS')
