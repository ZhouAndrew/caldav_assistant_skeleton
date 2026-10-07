#!/usr/bin/env python3
"""Drive Quick Capture in the unchanged XPI against isolated real WordPress/MariaDB.
Runtime directory holds Thunderbird, extracted distro tools, wpcli, WP and fixture DB.
Never point this script at a user's site or database.
"""
import ctypes,struct
import argparse,base64,hashlib,http.server,json,os,socket,ssl,subprocess,tempfile,threading,time,urllib.request,zipfile
from pathlib import Path
from marionette_driver.marionette import Marionette
p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--xpi',required=True);p.add_argument('--output',required=True);a=p.parse_args()
r=Path(a.runtime).resolve();xpi=Path(a.xpi).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
profile=Path(tempfile.mkdtemp(prefix='wp-integration-'))
footer_fixture=r/'wp/wp-content/mu-plugins/article-bottom-acceptance.php'
env={**os.environ,'LD_LIBRARY_PATH':str(r/'deps/usr/lib/x86_64-linux-gnu'),'DISPLAY':'127.0.0.1:97','DBUS_SESSION_BUS_ADDRESS':'disabled:','NO_AT_BRIDGE':'1','GTK_A11Y':'none','MOZ_DISABLE_CONTENT_SANDBOX':'1','MOZ_DISABLE_RDD_SANDBOX':'1'}
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
 client=Marionette(host='127.0.0.1',port=2828,socket_timeout=45);client.start_session();client.timeout.script=60
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
def paste():
 chrome("const w=Services.wm.getMostRecentWindow('mail:3pane');w.focus();w.document.getElementById('tabmail').selectedBrowser.focus();")
 ui("document.getElementById('quick-capture').focus();")
 client.set_context('chrome')
 client.actions.perform([{"type":"key","id":"paste-keyboard","actions":[{"type":"keyDown","value":"\ue009"},{"type":"keyDown","value":"v"},{"type":"keyUp","value":"v"},{"type":"keyUp","value":"\ue009"}]}])
def latest():
 return ui('return AssistantStorage.listAudit().then(rows=>rows.slice().reverse().find(r=>r.action==="wordpress.append-log")?.details);')
def receipt(previous):
 return wait(lambda:(lambda r:r if r and r['marker']!=previous else None)(latest()))
def preview_state():
 return chrome('''const done=arguments[arguments.length-1];const b=Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("tabmail").selectedBrowser;const f=b.browsingContext.children[0];f.currentWindowGlobal.getActor("MarionetteCommands").executeScript("return {url:location.href,text:document.body.innerText,height:document.documentElement.scrollHeight,y:scrollY,viewport:innerHeight,articleBottom:(document.querySelector(".entry-content, .wp-block-post-content")?.getBoundingClientRect().bottom ?? -9999)+scrollY,resources:[...document.querySelectorAll('img,a')].map(n=>n.src || n.href)};",[],{timeout:20000}).then(done,e=>done({error:String(e)}));''',[],True)
def verify_preview(result,previous_url=None):
 assert result['success'] and result['logSaved'],result
 assert any(step['name']=='append + read-back daily WordPress log' for step in result['steps']),result
 wait(lambda:ui('return document.getElementById("preview-status").textContent==="" && !document.getElementById("post-preview").hidden && (!arguments[0] || document.getElementById("post-preview").src !== arguments[0]);',[previous_url]))
 url=ui('return document.getElementById("post-preview").src;')
 assert '?refresh=' in url and (not previous_url or previous_url!=url),url
 assert ui('return document.getElementById("open-post").href;')==result['post']['link']
 state=preview_state();assert state['url']==url,state
 assert abs(state['y']-max(0,state['articleBottom']-state['viewport']))<=2,state
 content=json.loads(wp('post','get',str(result['post']['id']),'--format=json'))['post_content']
 assert result['marker'] in content and content.rfind('<!-- caldav-assistant-log-')==content.index('<!-- '+result['marker']+' -->'),content[-300:]
 assert 'CAPTURE REAL TEXT' in state['text'],state
 assert all(media['sourceUrl'] in state['resources'] for media in result['media']),state
 report.setdefault('captures',[]).append({'postId':result['post']['id'],'post_url':result['post']['link'],'media':result['media'],'preview':{k:v for k,v in state.items() if k not in ['text','resources']},'marker':result['marker']})
 return url

def drag(files,target='quick-capture'):
 # Native chrome drag source holds real nsIFile objects. Production XPI is untouched.
 ui('document.getElementById(arguments[0]).scrollIntoView({block:"center"});',[target])
 rect=ui('const r=document.getElementById(arguments[0]).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};',[target])
 position=chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");w.focus();const b=w.document.getElementById("tabmail").selectedBrowser;const r=b.getBoundingClientRect();w.__captureDragFiles=arguments[0];let source=w.document.getElementById("capture-drag-source");if(source)source.remove();source=w.document.createElementNS("http://www.w3.org/1999/xhtml","div");source.id="capture-drag-source";source.draggable=true;source.textContent="Acceptance file drag source";source.style.cssText="position:fixed;left:30px;top:130px;width:230px;height:40px;background:orange;color:black;z-index:999999";source.addEventListener("dragstart",event=>{w.__captureDragStarted=event.isTrusted;for(let i=0;i<w.__captureDragFiles.length;i++){const file=Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);file.initWithPath(w.__captureDragFiles[i]);event.dataTransfer.mozSetDataAt("application/x-moz-file",file,i);}event.dataTransfer.effectAllowed="copy";});w.document.documentElement.appendChild(source);return {x:r.x+arguments[1].x+w.mozInnerScreenX,y:r.y+arguments[1].y+w.mozInnerScreenY,sx:100+w.mozInnerScreenX,sy:150+w.mozInnerScreenY};''',[files,rect])
 # XTEST sends real pointer input through the X server (including GTK drag/drop).
 (out/('before-drag-'+target+'.png')).write_bytes(base64.b64decode(client.screenshot()))
 x=ctypes.CDLL('libX11.so.6');x.XOpenDisplay.argtypes=[ctypes.c_char_p];x.XOpenDisplay.restype=ctypes.c_void_p
 x.XQueryExtension.argtypes=[ctypes.c_void_p,ctypes.c_char_p,*([ctypes.POINTER(ctypes.c_int)]*3)]
 x._XGetRequest.argtypes=[ctypes.c_void_p,ctypes.c_ubyte,ctypes.c_size_t];x._XGetRequest.restype=ctypes.c_void_p
 x.XFlush.argtypes=[ctypes.c_void_p];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
 display=x.XOpenDisplay(env['DISPLAY'].encode());assert display
 opcode=ctypes.c_int();event=ctypes.c_int();error=ctypes.c_int()
 assert x.XQueryExtension(display,b'XTEST',ctypes.byref(opcode),ctypes.byref(event),ctypes.byref(error))
 def fake(kind,detail=0,px=0,py=0):
  data=bytearray(36);struct.pack_into('<BBHBBHI',data,0,opcode.value,2,9,kind,detail,0,0);struct.pack_into('<hh',data,24,round(px),round(py))
  request=x._XGetRequest(display,opcode.value,36);ctypes.memmove(request,bytes(data),36);x.XFlush(display);time.sleep(.05)
 fake(6,px=position['sx'],py=position['sy']);fake(4,1)
 for step in range(1,21):
  fake(6,px=position['sx']+(position['x']-position['sx'])*step/20,py=position['sy']+(position['y']-position['sy'])*step/20)
 fake(5,1);x.XCloseDisplay(display)
 assert chrome('return Services.wm.getMostRecentWindow("mail:3pane").__captureDragStarted;'),'Native file drag did not start'
 chrome('Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("capture-drag-source")?.remove();')

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
 footer_fixture.parent.mkdir(parents=True,exist_ok=True)
 footer_fixture.write_text('''<?php add_action("wp_footer", function() { echo '<footer style="height:1800px">ARTICLE BOTTOM ACCEPTANCE FOOTER</footer>'; });''')
 wp('option','update','home','https://localhost:18443');wp('option','update','siteurl','https://localhost:18443');wp('rewrite','flush')
 old_posts=wp('post','list','--post_type=post','--format=ids').split()
 if old_posts:wp('post','delete',*old_posts,'--force')
 report['wordpress']=wp('core','version');report['wpcli']=wp('--version')
 launch([str(r/'deps/usr/bin/Xvfb'),':97','-screen','0','1280x900x24','-nolisten','unix','-nolisten','local','-listen','tcp','-ac'],'xvfb.log')
 time.sleep(1)
 prefs={'marionette.enabled':True,'marionette.port':2828,'app.update.enabled':False,'mail.provider.suppress_dialog_on_startup':True,'mail.shell.checkDefaultClient':False,'xpinstall.signatures.required':False,'extensions.autoDisableScopes':0,'extensions.enabledScopes':15,'mailnews.start_page.enabled':False}
 (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)},{json.dumps(v)});' for k,v in prefs.items()))
 tb=start()
 install=chrome('''const done=arguments[arguments.length-1];(async()=>{const {AddonManager}=ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");const f=Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);f.initWithPath(arguments[0]);const i=await AddonManager.getInstallForFile(f);i.addListener({onInstallEnded(i,a){done({version:a.version,active:a.isActive});},onInstallFailed(i){done({error:i.error});}});await i.install();})().catch(e=>done({error:String(e)}));''',[str(xpi)],True)
 assert install.get('active'),install;check['XPIInstall']=True
 base=wait(lambda:chrome('''const {ExtensionParent}=ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");return ExtensionParent.GlobalManager.extensionMap.get("ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net")?.baseURI.spec;'''))
 report['thunderbird']=chrome('return Services.appinfo.version;')

 # HTTP avoids fixture TLS trust prompts; retain ordinary full public WordPress pages.
 wp('option','update','home','http://127.0.0.1:18880');wp('option','update','siteurl','http://127.0.0.1:18880')
 config('wp-cli','http://127.0.0.1:18880')
 page('workspace')
 wait(lambda:ui('return document.getElementById("preview-status").textContent==="今天尚无日志 Post。";'))
 assert wp('post','list','--post_type=post','--format=ids')==''
 assert not ui('return AssistantStorage.listWordPressOutbox();')
 check['EmptyPreviewDoesNotCreatePost']=True
 initial=int(wp('post','create','--post_title='+time.strftime('%B %-d %A %Y'),'--post_content=EXISTING POST BEFORE CAPTURE'+('<p>ARTICLE BODY LINE</p>'*80),'--post_status=publish','--porcelain'))
 # Reload without performing any capture: the independent component reads the existing Post.
 ui('location.reload();');wait(lambda:ui('return document.readyState==="complete";'))
 wait(lambda:ui('return !document.getElementById("post-preview").hidden && document.getElementById("preview-status").textContent==="";'))
 state=preview_state();assert 'EXISTING POST BEFORE CAPTURE' in state['text'] and abs(state['y']-max(0,state['articleBottom']-state['viewport']))<=2,state
 assert latest() is None
 assert not ui('return AssistantStorage.listWordPressOutbox();')
 assert wp('post','get',str(initial),'--field=post_content')=='EXISTING POST BEFORE CAPTURE'+('<p>ARTICLE BODY LINE</p>'*80)
 assert state['height']-state['viewport']-state['y']>1000,state
 check['ArticleEndExcludesLargeFooter']=True
 check['IndependentExistingPostOnOpen']=True
 ui('document.getElementById("quick-capture").closest("section").remove();document.getElementById("refresh-post").click();')
 wait(lambda:ui('return document.getElementById("preview-status").textContent==="";'))
 assert 'EXISTING POST BEFORE CAPTURE' in preview_state()['text']
 check['PreviewWithoutQuickCapture']=True
 ui('location.reload();');wait(lambda:ui('return document.readyState==="complete";'))
 last_url=ui('return document.getElementById("post-preview").src;')
 chrome('Cc["@mozilla.org/widget/clipboardhelper;1"].getService(Ci.nsIClipboardHelper).copyString("CAPTURE REAL TEXT");')
 paste();first=receipt(None);last_url=verify_preview(first,last_url);check['TrustedTextPaste']=True
 # Paste a real screenshot through the OS clipboard using Thunderbird's native image format.
 screenshot=client.screenshot()
 chrome('''const image=atob(arguments[0]);const img=Cc["@mozilla.org/image/tools;1"].getService(Ci.imgITools).decodeImageFromBuffer(image,image.length,"image/png");const t=Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);t.init(null);t.addDataFlavor("application/x-moz-nativeimage");t.setTransferData("application/x-moz-nativeimage",img);Services.clipboard.setData(t,null,Services.clipboard.kGlobalClipboard);''',[screenshot])
 paste();image=receipt(first['marker']);last_url=verify_preview(image,last_url);assert len(image['media'])==1 and image['media'][0]['mimeType'].startswith('image/'),image
 check['TrustedScreenshotPaste']=True
 file1=out/'capture-one.txt';file1.write_text('REAL SINGLE FILE')
 file2=out/'capture-two.txt';file2.write_text('REAL MULTI FILE')
 drag([str(file1)]);single=receipt(image['marker']);last_url=verify_preview(single,last_url);assert len(single['media'])==1,single;check['TrustedSingleFileDrop']=True
 drag([str(file1),str(file2)]);multi=receipt(single['marker']);last_url=verify_preview(multi,last_url);assert len(multi['media'])==2,multi;check['TrustedMultiFileDrop']=True
 # Native clipboard file transfer where the platform makes files available.
 chrome('''const f=Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);f.initWithPath(arguments[0]);const t=Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);t.init(null);t.addDataFlavor("application/x-moz-file");t.setTransferData("application/x-moz-file",f);Services.clipboard.setData(t,null,Services.clipboard.kGlobalClipboard);''',[str(file2)])
 paste();filepaste=receipt(multi['marker']);last_url=verify_preview(filepaste,last_url);assert len(filepaste['media'])==1,filepaste;check['TrustedClipboardFilePaste']=True
 before=wp('post','get',str(first['post']['id']),'--field=post_content')
 media_before=wp('post','list','--post_type=attachment','--format=ids')
 drag([str(file1)],'post-preview');time.sleep(2)
 assert wp('post','get',str(first['post']['id']),'--field=post_content')==before
 assert wp('post','list','--post_type=attachment','--format=ids')==media_before
 check['PreviewNativeDropNoUploadNoAppend']=True
 page('workspace')
 (out/'work-preview.png').write_bytes(base64.b64decode(client.screenshot()))
 # A real refused TCP connection retains the capture; currentWorkId stays unchanged.
 config('application-password','http://127.0.0.1:9');page('workspace')
 pointer_before=ui('return AssistantStorage.getCurrentWorkId();')
 chrome('Cc["@mozilla.org/widget/clipboardhelper;1"].getService(Ci.nsIClipboardHelper).copyString("CAPTURE REAL FAILURE");')
 paste();failed=receipt(filepaste['marker']);assert not failed['success'],failed
 assert len(ui('return AssistantStorage.listWordPressOutbox();'))==1
 assert 'Outbox' in ui('return document.getElementById("capture-result").textContent;')
 assert ui('return AssistantStorage.getCurrentWorkId();')==pointer_before
 check['RealOutageRetainedPointerUnchanged']=True
 report['success']=all(check.values());print(json.dumps(report,indent=2),flush=True)

except Exception as e:
 report['success']=False;report['error']=str(e);raise
finally:
 footer_fixture.unlink(missing_ok=True)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 if client:
  try:client.delete_session()
  except Exception:pass
 for q in reversed(processes):
  q.terminate()
  try:q.wait(timeout=10)
  except subprocess.TimeoutExpired:q.kill()
 for log in logs:log.close()
