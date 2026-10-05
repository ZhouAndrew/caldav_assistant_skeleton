#!/usr/bin/env python3
"""Drive the unmodified XPI UI against an isolated real WordPress/MariaDB fixture.
Runtime directory holds Thunderbird, extracted distro tools, wpcli, WP and fixture DB.
Never point this script at a user's site or database.
"""
import argparse,base64,hashlib,http.server,json,os,socket,ssl,subprocess,tempfile,threading,time,urllib.request,zipfile
from pathlib import Path
from marionette_driver.marionette import Marionette
p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--xpi',required=True);p.add_argument('--output',required=True);a=p.parse_args()
r=Path(a.runtime).resolve();xpi=Path(a.xpi).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
profile=Path(tempfile.mkdtemp(prefix='wp-integration-'))
env={**os.environ,'LD_LIBRARY_PATH':str(r/'deps/usr/lib/x86_64-linux-gnu'),'DISPLAY':'127.0.0.1:97','MOZ_DISABLE_CONTENT_SANDBOX':'1','MOZ_DISABLE_RDD_SANDBOX':'1'}
processes=[];logs=[];client=None;report={'sha256':hashlib.sha256(xpi.read_bytes()).hexdigest(),'build':json.loads(zipfile.ZipFile(xpi).read('build-info.json')),'checks':{}};check=report['checks']
def launch(cmd,name):
 log=(out/name).open('w');logs.append(log);q=subprocess.Popen(cmd,env=env,stdout=log,stderr=log);processes.append(q);return q
def wait(fn,seconds=45):
 deadline=time.monotonic()+seconds;error=None
 while time.monotonic()<deadline:
  try:
   value=fn()
   if value:return value
  except Exception as e:error=e
  time.sleep(.2)
 raise RuntimeError('Timed out: '+str(error))
def wp(*args):return subprocess.check_output([str(r/'wpcli'),'--path='+str(r/'wp'),*args],env=env,text=True).strip()
def chrome(script,args=None,async_=False):
 client.set_context('chrome')
 return (client.execute_async_script if async_ else client.execute_script)(script,script_args=args or [])
def start():
 q=launch([str(r/'thunderbird/thunderbird'),'-no-remote','-profile',str(profile),'--marionette','--remote-allow-system-access'],f'thunderbird-{len(processes)}.log')
 def ready():
  s=socket.socket();s.settimeout(.2)
  try:s.connect(('127.0.0.1',2828));return True
  finally:s.close()
 wait(ready)
 global client
 client=Marionette(host='127.0.0.1',port=2828);client.start_session();client.timeout.script=60
 return q
base=''
def page(name):
 chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");const t=w.document.getElementById("tabmail");const url=arguments[0];const found=t.tabInfo.findIndex(x=>x.browser?.currentURI?.spec===url);if(found>=0)t.switchToTab(found);else t.openTab("contentTab",{url,contentPage:url});''',[base+name+'.html'])
 wait(lambda:ui('return document.readyState === "complete";'))
def ui(script,args=None):
 value=chrome('''const done=arguments[arguments.length-1];const b=Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("tabmail").selectedBrowser;b.browsingContext.currentWindowGlobal.getActor("MarionetteCommands").executeScript(arguments[0],arguments[1],{timeout:60000}).then(done,e=>done({__error:String(e)}));''',[script,args or []],True)
 if isinstance(value,dict) and '__error' in value:raise RuntimeError(value['__error'])
 return value
def config(transport,url='https://localhost:18443'):
 page('wordpress')
 wait(lambda:ui('return document.getElementById("status").textContent.includes("WordPress URL");'))
 ui('''document.getElementById("save-result").textContent="";document.getElementById("wp-transport").value=arguments[0];document.getElementById("wp-url").value=arguments[1];document.getElementById("wp-user").value="acceptance";document.getElementById("wp-password").value=arguments[2];document.getElementById("wp-path").value=arguments[3];document.getElementById("wp-cli").value=arguments[4];document.getElementById("wp-daily-work-log").checked=false;document.getElementById("wp-allow-untrusted-tls").checked=arguments[1].startsWith("https");document.getElementById("save").click();''',[transport,url,(r/'wp-app-password.txt').read_text().strip(),str(r/'wp'),str(r/'wpcli')])
 wait(lambda:ui('return document.getElementById("save-result").textContent.includes("已保存");'))
 c=ui('return window.AssistantWordPress.getConfig();');assert c['transport']==transport and c['baseUrl']==url
 return c
def audit_result(action,previous=None):
 return wait(lambda:ui('''return window.AssistantStorage.listAudit().then(rows=>rows.slice().reverse().find(row=>row.action===arguments[0] && row.id!==arguments[1])?.details);''',[action,previous]))
def submit(text):
 page('record');wait(lambda:ui('return !document.getElementById("submit").disabled;'))
 previous=ui('return window.AssistantStorage.listAudit().then(rows=>rows.slice().reverse().find(row=>row.action==="wordpress.append-log")?.id);')
 ui('document.getElementById("content").value=arguments[0];document.getElementById("submit").click();',[text])
 wait(lambda:ui('return !document.getElementById("submit").disabled;'))
 return audit_result('wordpress.append-log',previous)
try:
 launch([str(r/'deps/usr/sbin/mariadbd'),'--no-defaults','--basedir='+str(r/'deps/usr'),'--datadir='+str(r/'mysql'),'--socket=','--port=13306','--bind-address=127.0.0.1','--user=root'],'mariadb.log')
 wait(lambda:subprocess.run([str(r/'deps/usr/bin/mariadb'),'--no-defaults','-h127.0.0.1','-P13306','-uroot','-e','SELECT 1;'],env=env,capture_output=True).returncode==0)
 # TLS reverse proxy and PHP serve only this private fixture.
 router=r/'wp/router-acceptance.php';router.write_text('<?php if(isset($_SERVER["HTTP_X_FORWARDED_PROTO"]) && $_SERVER["HTTP_X_FORWARDED_PROTO"] === "https") $_SERVER["HTTPS"]="on"; $path=parse_url($_SERVER["REQUEST_URI"],PHP_URL_PATH); if($path !== "/" && is_file(__DIR__.$path)) return false; require __DIR__."/index.php";')
 launch([str(r/'deps/usr/bin/php8.3'),'-c',str(r/'php.ini'),'-S','127.0.0.1:18880','-t',str(r/'wp'),str(router)],'php.log')
 cert=r/'acceptance.crt';key=r/'acceptance.key'
 if not cert.exists():subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','2','-subj','/CN=localhost'],check=True,capture_output=True)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 class Proxy(http.server.BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def handle_request(self):
   body=self.rfile.read(int(self.headers.get('Content-Length',0))) or None
   headers={k:v for k,v in self.headers.items() if k.lower() not in ['host','connection']};headers['X-Forwarded-Proto']='https'
   req=urllib.request.Request('http://127.0.0.1:18880'+self.path,data=body,method=self.command,headers=headers)
   try:response=opener.open(req,timeout=30)
   except urllib.error.HTTPError as e:response=e
   data=response.read();self.send_response(response.status)
   for k,v in response.headers.items():
    if k.lower() not in ['transfer-encoding','connection','content-length']:self.send_header(k,v)
   self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  do_GET=do_POST=do_DELETE=do_PUT=handle_request
 server=http.server.ThreadingHTTPServer(('127.0.0.1',18443),Proxy);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key);server.socket=ctx.wrap_socket(server.socket,server_side=True);threading.Thread(target=server.serve_forever,daemon=True).start()
 assert wp('option','get','blogname') == 'Isolated Acceptance', 'Refusing a non-fixture site'
 wp('option','update','home','https://localhost:18443');wp('option','update','siteurl','https://localhost:18443');wp('rewrite','flush')
 old_posts=wp('post','list','--post_type=post','--format=ids').split()
 if old_posts:wp('post','delete',*old_posts,'--force')
 report['wordpress']=wp('core','version');report['wpcli']=wp('--version')
 launch([str(r/'deps/usr/bin/Xvfb'),':97','-screen','0','1280x900x24','-nolisten','unix','-nolisten','local','-listen','tcp','-ac'],'xvfb.log')
 prefs={'marionette.enabled':True,'marionette.port':2828,'app.update.enabled':False,'mail.provider.suppress_dialog_on_startup':True,'mail.shell.checkDefaultClient':False,'xpinstall.signatures.required':False,'extensions.autoDisableScopes':0,'extensions.enabledScopes':15,'mailnews.start_page.enabled':False}
 (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)},{json.dumps(v)});' for k,v in prefs.items()))
 tb=start()
 install=chrome('''const done=arguments[arguments.length-1];(async()=>{const {AddonManager}=ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");const f=Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);f.initWithPath(arguments[0]);const i=await AddonManager.getInstallForFile(f);i.addListener({onInstallEnded(i,a){done({version:a.version,active:a.isActive});},onInstallFailed(i){done({error:i.error});}});await i.install();})().catch(e=>done({error:String(e)}));''',[str(xpi)],True)
 assert install.get('active'),install;check['XPIInstall']=True
 base=wait(lambda:chrome('''const {ExtensionParent}=ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");return ExtensionParent.GlobalManager.extensionMap.get("ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net")?.baseURI.spec;'''))
 report['thunderbird']=chrome('return Services.appinfo.version;')
 for transport in ['wp-cli','application-password']:
  config(transport)
  ui('document.getElementById("quick").click();')
  quick=wait(lambda:ui('const p=document.querySelector("#test-result pre");if(!p)return null;const r=JSON.parse(p.textContent);return r.action==="connection.wordpress-quick"?r:null;'))
  assert quick['success'],quick;assert quick['transport']==transport,quick;check[transport+' connection']=True
  if transport=='application-password':assert quick['tlsVerification']=='disabled-local';check['SelfSignedTLS']=True
  ui('document.getElementById("full").click();')
  full=wait(lambda:ui('const p=document.querySelector("#test-result pre");if(!p)return null;const r=JSON.parse(p.textContent);return r.action==="connection.wordpress-dual-write"?r:null;'))
  assert full['success'],full;check[transport+' full read/write/media/cleanup']=True
  first=submit('INTEGRATION '+transport+' first');assert first['success'],first
  second=submit('INTEGRATION '+transport+' second');assert second['success'] and first['post']['id']==second['post']['id'],second
  post=json.loads(wp('post','get',str(first['post']['id']),'--format=json'));assert 'first' in post['post_content'] and 'second' in post['post_content'];check[transport+' real manual log + same day']=True
  print('REAL',transport,'PASS',flush=True)
 # Multiple candidates -> four retained user logs -> explicit selection -> verified retry.
 day=time.strftime('%Y-%m-%d');date_title=first['post']['title'];chosen=first['post']['id']
 other=int(wp('post','create','--post_title='+date_title,'--post_content=UNCHANGED OTHER CANDIDATE','--post_status=draft','--porcelain'))
 for n in range(4):assert not submit('AMBIGUOUS LOG '+str(n))['success']
 assert len(ui('return window.AssistantStorage.listWordPressOutbox();'))==4;check['Ambiguous4Retained']=True
 page('wordpress');ui('document.getElementById("retry-outbox").click();');wait(lambda:ui('return !document.getElementById("retry-outbox").disabled && document.querySelector("#daily-targets select");'))
 ui('''const s=document.querySelector("#daily-targets select");s.value=arguments[0];s.dispatchEvent(new Event("change"));document.querySelector("#daily-targets button").click();''',[str(chosen)])
 wait(lambda:ui('return window.AssistantStorage.listWordPressOutbox().then(rows=>rows.length === 0);'))
 assert json.loads(wp('post','get',str(other),'--format=json'))['post_content']=='UNCHANGED OTHER CANDIDATE'
 post=json.loads(wp('post','get',str(chosen),'--format=json'));assert all('AMBIGUOUS LOG '+str(n) in post['post_content'] for n in range(4));check['ExplicitSelection4Recovered']=True
 (out/'daily-target-ui.png').write_bytes(base64.b64decode(client.screenshot()))
 # Real outage is a refused TCP connection, not a mocked transport.
 config('application-password','http://127.0.0.1:9');failure=submit('REAL OUTAGE RETAINED');assert not failure['success'];assert len(ui('return window.AssistantStorage.listWordPressOutbox();'))==1
 check['RealOutageRetained']=True
 client.delete_session();client=None;tb.terminate();tb.wait(timeout=20);tb=start()
 base=wait(lambda:chrome('''const {ExtensionParent}=ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");return ExtensionParent.GlobalManager.extensionMap.get("ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net")?.baseURI.spec;'''))
 page('wordpress');assert len(ui('return window.AssistantStorage.listWordPressOutbox();'))==1;check['OutboxSurvivesThunderbirdRestart']=True
 config('application-password');ui('document.getElementById("retry-outbox").click();');wait(lambda:ui('return !document.getElementById("retry-outbox").disabled;'));assert not ui('return window.AssistantStorage.listWordPressOutbox();');check['RealRecoveryRetry']=True
 post=json.loads(wp('post','get',str(chosen),'--format=json'));assert post['post_content'].count('REAL OUTAGE RETAINED')==1;check['NoDuplicateOnRecovery']=True
 # Historical date retry must use its own original daily post.
 historical=ui('return window.AssistantWordPress.createLog({content:"Historical integration log",date:new Date("2026-09-01T10:00:00"),marker:"historical-integration-marker"});');assert historical['success'];assert 'September 1' in historical['post']['title'];check['OriginalDateRetained']=True
 report['success']=all(check.values());print(json.dumps(report,indent=2),flush=True)
except Exception as e:
 report['success']=False;report['error']=str(e);raise
finally:
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 if client:
  try:client.delete_session()
  except Exception:pass
 for q in reversed(processes):
  q.terminate()
  try:q.wait(timeout=10)
  except subprocess.TimeoutExpired:q.kill()
 for log in logs:log.close()
