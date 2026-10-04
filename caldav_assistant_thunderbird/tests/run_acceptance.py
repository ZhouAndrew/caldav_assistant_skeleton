from pathlib import Path
import subprocess,json,os
root=Path(__file__).resolve().parents[1]
env={**os.environ,**json.loads((root/'artifacts/fixture-env.json').read_text())}
subprocess.run(['node','--test',*map(str,(root/'tests').glob('*.test.mjs'))],check=True)
subprocess.run(['python',str(root/'tools/package.py')],check=True)
env['ACCEPTANCE_XPI']=str(root/'artifacts/CalDAV-Assistant-cleanroom-0.4.0-candidate.xpi')
for script in ['real_thunderbird.py','run_wordpress.py']:
 subprocess.run(['python',str(root/'tests'/script)],env=env,check=True)
