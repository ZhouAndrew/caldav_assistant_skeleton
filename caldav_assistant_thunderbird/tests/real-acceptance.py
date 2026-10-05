#!/usr/bin/env python3
"""Install the unchanged deliverable in Thunderbird; drive native Tasks and Work UI.
All services/processes run in this process's network namespace and isolated temp dirs.
"""
import argparse, hashlib, json, os, shutil, socket, subprocess, tempfile, time, urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone
from marionette_driver.marionette import Marionette

parser=argparse.ArgumentParser()
parser.add_argument('--thunderbird',required=True)
parser.add_argument('--xvfb',default='Xvfb')
parser.add_argument('--xpi',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='caldav-assistant-040-'))
profile=root/'profile';profile.mkdir()
processes=[];logs=[];report={'xpi':str(Path(args.xpi).resolve()),'sha256':hashlib.sha256(Path(args.xpi).read_bytes()).hexdigest(),'checks':{}}
client=None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def http(method,path,data=None,content_type='text/calendar'):
 req=urllib.request.Request('http://127.0.0.1:15232'+path,data=data.encode() if isinstance(data,str) else data,method=method,headers={'Content-Type':content_type,'Authorization':'Basic YWNjZXB0YW5jZTp0ZXN0LXBhc3N3b3Jk'})
 with opener.open(req,timeout=15) as response:return response.status,response.read().decode()
def wait(test,seconds=30):
 deadline=time.monotonic()+seconds
 last=None
 while time.monotonic()<deadline:
  try:
   value=test()
   if value:return value
  except Exception as e:last=e
  time.sleep(.2)
 raise RuntimeError('Timed out: '+str(last))
def launch(command,name,env=None):
 log=(output/name).open('w');logs.append(log)
 p=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env);processes.append(p);return p

def chrome(script,args=None,async_=False):
 client.set_context('chrome')
 return (client.execute_async_script if async_ else client.execute_script)(script,script_args=args or [],script_timeout=30000) if async_ else client.execute_script(script,script_args=args or [])

def start_tb():
 env=os.environ.copy();env.update(DISPLAY='127.0.0.1:98',MOZ_DISABLE_CONTENT_SANDBOX='1',MOZ_DISABLE_RDD_SANDBOX='1',MOZ_DISABLE_GMP_SANDBOX='1')
 p=launch([args.thunderbird,'-no-remote','-profile',str(profile),'--marionette','--remote-allow-system-access'],'thunderbird-'+str(len(processes))+'.log',env)
 def connect():
  if p.poll() is not None:raise RuntimeError('Thunderbird exited '+str(p.returncode))
  s=socket.socket();s.settimeout(.3)
  try:s.connect(('127.0.0.1',2828));return True
  finally:s.close()
 wait(connect,45)
 global client
 client=Marionette(host='127.0.0.1',port=2828);client.start_session();client.timeout.script=30
 return p

try:
 (root/'rights').write_text('[all]\nuser = .*\ncollection = .*\npermissions = RrWw\n')
 (root/'radicale.conf').write_text(f'[server]\nhosts = 127.0.0.1:15232\n[auth]\ntype = none\n[rights]\ntype = from_file\nfile = {root}/rights\n[storage]\nfilesystem_folder = {root}/data\n[logging]\nlevel = debug\n')
 radicale=launch([os.sys.executable,'-m','radicale','--config',str(root/'radicale.conf')],'radicale.log')
 wait(lambda:http('GET','/')[0]==200)
 http('MKCALENDAR','/acceptance/calendar/','''<?xml version="1.0"?><C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:set><D:prop><D:displayname>Assistant isolated acceptance</D:displayname><C:supported-calendar-component-set><C:comp name="VTODO"/><C:comp name="VEVENT"/></C:supported-calendar-component-set></D:prop></D:set></C:mkcalendar>''','application/xml')
 for uid,title in [('seed-a','Acceptance A'),('seed-b','Acceptance B'),('seed-c','Acceptance C')]:
  data=f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Acceptance//EN\r\nBEGIN:VTODO\r\nUID:{uid}\r\nDTSTAMP:20261005T000000Z\r\nSUMMARY:{title}\r\nSTATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:35\r\nDESCRIPTION:Original user text\r\nEND:VTODO\r\nEND:VCALENDAR\r\n'
  http('PUT',f'/acceptance/calendar/{uid}.ics',data)
 launch([args.xvfb,':98','-screen','0','1280x900x24','-nolisten','unix','-nolisten','local','-listen','tcp','-ac'],'xvfb.log')
 prefs={'marionette.enabled':True,'marionette.port':2828,'app.update.enabled':False,'mail.provider.suppress_dialog_on_startup':True,'mail.shell.checkDefaultClient':False,'browser.shell.checkDefaultBrowser':False,'xpinstall.signatures.required':False,'extensions.autoDisableScopes':0,'extensions.enabledScopes':15,'mailnews.start_page.enabled':False,'mailnews.start_page.override_url':'about:blank','mailnews.start_page.url':'about:blank','calendar.registry.acceptance-calendar.name':'Acceptance','calendar.registry.acceptance-calendar.type':'caldav','calendar.registry.acceptance-calendar.username':'acceptance','calendar.registry.acceptance-calendar.uri':'http://acceptance:test-password@127.0.0.1:15232/acceptance/calendar/','calendar.registry.acceptance-calendar.calendar-main-in-composite':True,'calendar.registry.acceptance-calendar.calendar-main-default':True,'calendar.registry.acceptance-calendar.cache.enabled':True,'calendar.list.sortOrder':'acceptance-calendar','calendar.timezone.local':'Asia/Shanghai'}
 (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)}, {json.dumps(v)});' for k,v in prefs.items()))
 tb=start_tb();report['checks']['ThunderbirdStarts']=True
 print('CAPABILITIES',client.session,flush=True)
 install=chrome('''const done=arguments[arguments.length-1];(async()=>{const {AddonManager}=ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");const f=Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);f.initWithPath(arguments[0]);const install=await AddonManager.getInstallForFile(f);install.addListener({onInstallEnded(i,a){done({id:a.id,version:a.version,active:a.isActive})},onInstallFailed(i){done({error:i.error})}});await install.install();})().catch(e=>done({error:String(e),stack:e.stack}));''',[str(Path(args.xpi).resolve())],True)
 print('INSTALL',install,flush=True);assert install.get('version')=='0.4.0',install;report['checks']['XPIInstall']=True
 report['thunderbird']=chrome('return Services.appinfo.version;')
 result=chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");return {url:w?.location.href,taskTree:!!w?.document.getElementById("calendar-task-tree"),tabs:w?.document.getElementById("tabmail")?.tabInfo.map(t=>({mode:t.mode.name,url:t.browser?.currentURI?.spec}))};''')
 print('WINDOW',result,flush=True)
 chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");w.calSwitchToTaskMode();''')
 result=wait(lambda:chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");const t=w.document.getElementById("calendar-task-tree");if(!t.__acceptanceFilter){t.__acceptanceFilter=true;t.updateFilter("all");}return t.mTaskArray?.length ? t.mTaskArray.map(x=>({id:x.id,title:x.title,recurrenceId:x.recurrenceId?.icalString || ""})):null;'''),45)
 print('TASKS',result,flush=True)
 ext=chrome('''const {ExtensionParent}=ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");const ext=ExtensionParent.GlobalManager.extensionMap.get("ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net");return {base:ext.baseURI.spec,views:[...ext.views].map(v=>({type:v.viewType,url:v.url,keys:Object.keys(v)}))};''')
 print('EXT',ext,flush=True);report['checks']['AddonLoads']=True
 chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");w.document.getElementById("tabmail").openTab("contentTab",{contentPage:arguments[0],url:arguments[0]});''',[ext['base']+'workspace.html'])
 def work(script,script_args=None):
  return chrome('''const done=arguments[arguments.length-1];const b=Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("tabmail").selectedBrowser;b.browsingContext.currentWindowGlobal.getActor("MarionetteCommands").executeScript(arguments[0],arguments[1],{timeout:20000}).then(done,e=>done({__error:String(e)}));''',[script,script_args or []],True)
 def select(ids):
  result=chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");const t=w.document.getElementById("calendar-task-tree");t.mTreeView.selection.clearSelection();for(const uid of arguments[0]){const i=t.mTaskArray.findIndex(x=>x.id===uid);if(i<0)throw new Error("Missing native row "+uid);t.mTreeView.selection.rangedSelect(i,i,true);}return t.selectedTasks.map(x=>({id:x.id,recurrenceId:x.recurrenceId?.icalString || ""}));''',[ids]);assert len(result)==len(ids),result;return result
 def ui():
  result=work('''return {disabled:document.getElementById("start-button").disabled,selection:document.getElementById("selection-status").textContent,currentHidden:document.getElementById("current-work").hidden,title:document.getElementById("current-title").textContent,notice:document.getElementById("notice").textContent};''')
  assert '__error' not in result,result
  return result
 def storage():
  result=work('return window.browser.storage.local.get(["caldavAssistant.currentWorkId","caldavAssistant.lastReceipt"]);')
  assert '__error' not in result,result
  return result
 def click(action,success=True):
  previous=storage().get('caldavAssistant.lastReceipt',{}).get('id')
  if action=='start':script='document.getElementById("start-button").click();'
  elif action=='cancel':script='document.querySelector("[data-action=cancel]").click();document.getElementById("cancel-confirm-yes").click();'
  else:script=f'document.querySelector("[data-action={action}]").click();'
  work(script)
  result=wait(lambda: (lambda r:r if r and r.get('id')!=previous else None)(storage().get('caldavAssistant.lastReceipt')))
  assert result['action']==action,result
  assert result['success']==success,result
  if success:
   assert result['verified'],result
   assert result['actual']['status']==result['expected']['status'],result
   assert result['actual']['description']==result['expected']['description'],result
  print('ACTION',action,'PASS',result.get('target'),flush=True)
  report.setdefault('receipts',[]).append(result)
  return result
 def server_compare(receipt):
  import vobject
  _,text=http('GET',f"/acceptance/calendar/{receipt['target']['id']}.ics")
  calendar=vobject.readOne(text)
  target=receipt['target'].get('recurrenceId','')
  todos=calendar.vtodo_list
  def rid(t):
   value=getattr(t,'recurrence_id',None)
   if value is None:return ''
   value=value.value
   return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ') if hasattr(value,'tzinfo') and value.tzinfo else value.strftime('%Y%m%dT%H%M%S')
  matches=[t for t in todos if rid(t)==target]
  assert len(matches)==1,(target,text)
  t=matches[0];assert t.uid.value==receipt['target']['id']
  expected=receipt['expected']
  assert getattr(t,'status',None).value==expected['status'],text
  assert (int(t.percent_complete.value) if hasattr(t,'percent_complete') else 0)==expected['percentComplete'],text
  assert t.description.value==expected['description'],text
  report.setdefault('serverReadbacks',[]).append({'action':receipt['action'],'uid':t.uid.value,'recurrenceId':target,'status':t.status.value,'percentComplete':(int(t.percent_complete.value) if hasattr(t,'percent_complete') else 0),'descriptionMatches':True})
 # The visible Work DOM comes from the unchanged installed package.
 wait(lambda:'start-button' in work('return document.body.innerHTML;'))
 report['checks']['WorkUI']=True
 select([]);wait(lambda:ui()['disabled']);report['checks']['selection0']=True
 select(['seed-a']);wait(lambda:not ui()['disabled'] and 'Acceptance A' in ui()['selection']);report['checks']['selection1']=True
 select(['seed-a','seed-b']);wait(lambda:ui()['disabled']);report['checks']['selectionMany']=True
 select(['seed-b']);wait(lambda:not ui()['disabled'] and 'Acceptance B' in ui()['selection']);report['checks']['selectionRefresh']=True
 select(['seed-a']);wait(lambda:not ui()['disabled'] and 'Acceptance A' in ui()['selection'])
 # Change native selection and click the still-rendered A button in the same command.
 previous=storage().get('caldavAssistant.lastReceipt',{}).get('id')
 chrome('''const done=arguments[arguments.length-1];const w=Services.wm.getMostRecentWindow("mail:3pane");const t=w.document.getElementById("calendar-task-tree");t.mTreeView.selection.select(t.mTaskArray.findIndex(x=>x.id==="seed-b"));const b=w.document.getElementById("tabmail").selectedBrowser;b.browsingContext.currentWindowGlobal.getActor("MarionetteCommands").executeScript('document.getElementById("start-button").click();return document.getElementById("selection-status").textContent;',[],{timeout:20000}).then(done);''',[],True)
 stale=wait(lambda:(lambda r:r if r and r.get('id')!=previous else None)(storage().get('caldavAssistant.lastReceipt')))
 assert not stale['success'] and 'selection changed' in stale['error'],stale
 assert storage().get('caldavAssistant.currentWorkId') is None
 assert 'STATUS:NEEDS-ACTION' in http('GET','/acceptance/calendar/seed-a.ics')[1]
 assert 'STATUS:NEEDS-ACTION' in http('GET','/acceptance/calendar/seed-b.ics')[1]
 report['checks']['TOCTOU']=True
 select(['seed-a']);wait(lambda:not ui()['disabled'] and 'Acceptance A' in ui()['selection'])
 # Server changes after selection must override the native cached Task data.
 latest=http('GET','/acceptance/calendar/seed-a.ics')[1].replace('PERCENT-COMPLETE:35','PERCENT-COMPLETE:41')
 http('PUT','/acceptance/calendar/seed-a.ics',latest)
 started=click('start');server_compare(started);assert started['expected']['percentComplete']==41;report['checks']['LatestServerTask']=True;report['checks']['Start']=True
 wait(lambda:not ui()['currentHidden'] and ui()['title']=='Acceptance A')
 # Selection B while active cannot enable another Start.
 select(['seed-b']);wait(lambda:ui()['disabled']);assert storage()['caldavAssistant.currentWorkId']==started['target']['calendarId']+'|seed-a|'
 report['checks']['secondStartGuard']=True
 stopped=click('stop');server_compare(stopped);assert storage()['caldavAssistant.currentWorkId'] is None;report['checks']['Stop']=True
 for uid,action in [('seed-b','complete'),('seed-c','cancel')]:
  select([uid]);wait(lambda:not ui()['disabled'] and ('Acceptance B' if uid=='seed-b' else 'Acceptance C') in ui()['selection']);server_compare(click('start'));wait(lambda:not ui()['currentHidden']);server_compare(click(action));report['checks'][action.capitalize()]=True
 # Native recurring occurrence expansion, with real RECURRENCE-ID verification.
 stamp=datetime.now(timezone.utc).strftime('%Y%m%d')+'T090000Z'
 recur=f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Acceptance//EN\r\nBEGIN:VTODO\r\nUID:recurring\r\nDTSTAMP:{stamp}\r\nDTSTART:{stamp}\r\nDUE:{stamp}\r\nRRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Acceptance Recurring\r\nSTATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0\r\nDESCRIPTION:Original recurring text\r\nEND:VTODO\r\nEND:VCALENDAR\r\n'
 http('PUT','/acceptance/calendar/recurring.ics',recur)
 chrome('''const {cal}=ChromeUtils.importESModule("resource:///modules/calendar/calUtils.sys.mjs");cal.manager.getCalendarById("acceptance-calendar").refresh();Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("calendar-task-tree").updateFilter("throughsevendays");''')
 recurring_rows=wait(lambda:chrome('''const t=Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("calendar-task-tree");return t.mTaskArray.filter(x=>x.id==="recurring" && x.recurrenceId).map(x=>x.recurrenceId.icalString);''') or None)
 assert recurring_rows,recurring_rows
 select(['recurring']);wait(lambda:not ui()['disabled'] and 'Acceptance Recurring' in ui()['selection']);rec_start=click('start');assert rec_start['target']['recurrenceId'];server_compare(rec_start);wait(lambda:not ui()['currentHidden']);server_compare(click('stop'));report['checks']['Recurring']=True
 # Restart is a genuine process exit followed by the same isolated profile.
 chrome('''Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("calendar-task-tree").updateFilter("all");''')
 wait(lambda:chrome('return Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("calendar-task-tree").mTaskArray.some(x=>x.id==="seed-a");'))
 select(['seed-a']);wait(lambda:not ui()['disabled'] and 'Acceptance A' in ui()['selection']);before_restart=click('start');server_compare(before_restart)
 pointer=storage()['caldavAssistant.currentWorkId'];client.delete_session();client=None
 tb.terminate();tb.wait(timeout=20);assert tb.poll() is not None
 tb=start_tb()
 ext_base=wait(lambda:chrome('''const {ExtensionParent}=ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");return ExtensionParent.GlobalManager.extensionMap.get("ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net")?.baseURI.spec;'''))
 chrome('''Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("tabmail").openTab("contentTab",{url:arguments[0],contentPage:arguments[0]});''',[ext_base+'workspace.html'])
 wait(lambda:not ui()['currentHidden'] and ui()['title']=='Acceptance A')
 assert storage()['caldavAssistant.currentWorkId']==pointer
 server_compare(click('stop'));report['checks']['Restart']=True
 # Offline CalDAV cannot produce success from its local cache.
 chrome('''const w=Services.wm.getMostRecentWindow("mail:3pane");w.calSwitchToTaskMode();w.document.getElementById("calendar-task-tree").updateFilter("all");''')
 wait(lambda:chrome('return Services.wm.getMostRecentWindow("mail:3pane").document.getElementById("calendar-task-tree").mTaskArray.some(x=>x.id==="seed-a");'))
 select(['seed-a']);wait(lambda:not ui()['disabled'] and 'Acceptance A' in ui()['selection'])
 chrome('Services.io.offline=true;')
 wait(lambda:not ui()['disabled'] and 'Acceptance A' in ui()['selection'])
 failed=click('start',False);assert not failed['verified'] and storage()['caldavAssistant.currentWorkId'] is None
 chrome('Services.io.offline=false;')
 assert 'STATUS:NEEDS-ACTION' in http('GET','/acceptance/calendar/seed-a.ics')[1]
 report['checks']['OfflineReject']=True
 # Remove only this isolated collection and verify its actual absence.
 http('DELETE','/acceptance/calendar/')
 import urllib.error
 try:http('GET','/acceptance/calendar/');raise AssertionError('test collection remains')
 except urllib.error.HTTPError as e:assert e.code==404,e
 report['checks']['Cleanup']=True
 report['checks']['RealRadicale']=True
 report['checks']['RealThunderbird']=True
 print('REAL THUNDERBIRD / RADICALE ACCEPTANCE: PASS',flush=True)
except Exception as e:
 import traceback
 report['error']=str(e);report['traceback']=traceback.format_exc();print(report['traceback'],flush=True)
finally:
 if client:
  try:client.delete_session()
  except Exception:pass
 for p in reversed(processes):
  if p.poll() is None:
   p.terminate()
   try:p.wait(timeout=10)
   except subprocess.TimeoutExpired:p.kill();p.wait()
 for l in logs:l.close()
 (output/'report.json').write_text(json.dumps(report,indent=2))
 shutil.rmtree(root)
print(json.dumps({k:v for k,v in report.items() if k not in ('receipts','serverReadbacks','traceback')},indent=2))
if 'error' in report:raise SystemExit(1)
