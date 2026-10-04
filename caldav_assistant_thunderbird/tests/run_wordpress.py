import subprocess,os,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
wp=os.environ['WP_EXECUTABLE'];path=os.environ['WP_PATH'];php=os.environ['PHP_EXECUTABLE'];ini=os.environ['PHP_INI'];router=os.environ['WP_ROUTER']
server=subprocess.Popen([php,'-c',ini,'-S','127.0.0.1:18080','-t',path,router],stdout=(root/'artifacts/wordpress-http.log').open('w'),stderr=subprocess.STDOUT)
try:
 password=subprocess.check_output([wp,'--path='+path,'user','application-password','create','1','Acceptance node','--porcelain'],text=True).strip()
 root.joinpath('artifacts/real-wordpress-result.json').unlink(missing_ok=True)
 env={**os.environ,'WP_TEST_PASSWORD':password,'WP_TEST_URL':'http://127.0.0.1:18080'}
 time.sleep(.2)
 result=subprocess.run(['node',str(root/'tests/wordpress-real.mjs')],env=env,capture_output=True,text=True)
 print(result.stdout);print(result.stderr)
 if result.returncode:raise SystemExit(result.returncode)
 root.joinpath('artifacts/real-wordpress-result.json').write_text(result.stdout)
finally:server.terminate();server.wait()
