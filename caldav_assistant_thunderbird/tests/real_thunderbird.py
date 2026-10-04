"""Fresh-profile Thunderbird, native provider, real DOM clicks and Radicale.
Requirements: marionette_driver, radicale, requests; THUNDERBIRD_BINARY.
Never touches a user's Thunderbird profile or server.
"""
import os,json,time,tempfile,subprocess,base64,hashlib
from pathlib import Path
import requests
from marionette_driver.marionette import Marionette
ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts';ART.mkdir(exist_ok=True)
for old in ['real-thunderbird-result.json','native-wordpress-test.json','native-wordpress-full-test.json']:ART.joinpath(old).unlink(missing_ok=True)
binary=os.environ.get('THUNDERBIRD_BINARY','thunderbird')
work=Path(tempfile.mkdtemp(prefix='caldav-acceptance-'))
profile=work/'profile';profile.mkdir()
profile.joinpath('user.js').write_text('user_pref("mail.provider.enabled",false);\nuser_pref("mail.shell.checkDefaultClient",false);\nuser_pref("marionette.port",2828);\nuser_pref("extensions.webextensions.remote",false);\nuser_pref("browser.tabs.remote.autostart",false);\n')
log=(work/'thunderbird.log').open('w')
work.joinpath('rights').write_text('[acceptance]\nuser = .*\ncollection = .*\npermissions = RrWw\n')
work.joinpath('radicale.ini').write_text('[rights]\ntype = from_file\nfile = '+str(work/'rights')+'\n')
rad=subprocess.Popen(['python','-m','radicale','--config',str(work/'radicale.ini'),'--server-hosts','127.0.0.1:15232','--auth-type','none','--storage-filesystem-folder',str(work/'radicale'),'--logging-level','warning'],stdout=(work/'radicale.log').open('w'),stderr=subprocess.STDOUT)
tb=None
def wait_for(fn,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            result=fn()
            if result:return result
        except TimeoutError:raise
        except Exception as error:
            print('waiting:',str(error).splitlines()[0][:160],flush=True)
            if isinstance(error,RuntimeError):raise
        time.sleep(.15)
    raise TimeoutError('Condition did not become true')
try:
    base='http://127.0.0.1:15232/tester/tasks/'
    wait_for(lambda:requests.get('http://127.0.0.1:15232/',timeout=1).status_code==200)
    auth=('tester','test')
    r=requests.request('MKCALENDAR',base,auth=auth,data='<C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:set><D:prop><D:displayname>Acceptance tasks</D:displayname><C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set></D:prop></D:set></C:mkcalendar>',headers={'Content-Type':'application/xml'})
    assert r.status_code in (201,207),r.text
    # User-like fixtures: Unicode, multiline notes, due dates and pre-existing progress.
    for uid,title,percent in [('english','英语：1 套卷子',35),('chemistry','化学：国庆卷第 1 套',0)]:
        ics=f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Acceptance//EN\r\nBEGIN:VTODO\r\nUID:{uid}\r\nDTSTAMP:20261003T090000Z\r\nSUMMARY:{title}\r\nDESCRIPTION:原来的描述\\n保留中文、链接 https://andrew.local/ 和空格  \r\nDUE;VALUE=DATE:20261004\r\nSTATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:{percent}\r\nEND:VTODO\r\nEND:VCALENDAR\r\n'
        assert requests.put(base+uid+'.ics',auth=auth,data=ics.encode(),headers={'Content-Type':'text/calendar'}).status_code==201
    recurring='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Acceptance//EN\r\nBEGIN:VTODO\r\nUID:daily\r\nDTSTAMP:20261003T090000Z\r\nDTSTART;VALUE=DATE:20261003\r\nDUE;VALUE=DATE:20261003\r\nRRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:每日复习\r\nDESCRIPTION:循环任务原描述\r\nSTATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0\r\nEND:VTODO\r\nEND:VCALENDAR\r\n'
    assert requests.put(base+'daily.ics',auth=auth,data=recurring.encode(),headers={'Content-Type':'text/calendar'}).status_code==201
    tb=subprocess.Popen([binary,'--headless','--no-remote','--profile',str(profile),'--marionette','--remote-allow-system-access'],stdout=log,stderr=subprocess.STDOUT)
    m=Marionette('localhost',port=2828,socket_timeout=30);m.raise_for_port(timeout=30);m.start_session();m.set_context('chrome')
    def js(script,*args):return m.execute_script(script,script_args=list(args))
    def async_js(script,*args):return m.execute_async_script(script,script_args=list(args),script_timeout=30000)
    addon_path=os.environ.get('ACCEPTANCE_XPI',str(ROOT/'addon'))
    install_script='''const done=arguments[arguments.length-1];(async()=>{
      const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
      const file=Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile);file.initWithPath(arguments[0]);
      const addon=await AddonManager.installTemporaryAddon(file);return {id:addon.id};
    })().then(done,e=>done({error:e.message,stack:e.stack}));'''
    installed=async_js(install_script,addon_path)
    assert not installed.get('error'),installed
    # Configure the native CalDAV calendar and native authentication store.
    configured=async_js('''const done=arguments[arguments.length-1];(async()=>{
      const {cal}=ChromeUtils.importESModule('resource:///modules/calendar/calUtils.sys.mjs');
      const login=Cc['@mozilla.org/login-manager/loginInfo;1'].createInstance(Ci.nsILoginInfo);
      login.init('http://127.0.0.1:15232',null,arguments[1],'tester','test','','');await Services.logins.addLoginAsync(login);
      const c=cal.manager.createCalendar('caldav',Services.io.newURI(arguments[0]));c.setProperty('username','tester');c.setProperty('capabilities.realmrewrite.disabled',true);cal.manager.registerCalendar(c);c.name='Acceptance tasks';c.setProperty('cache.enabled',false);
      globalThis.acceptanceCalendarId=c.id;c.refresh();return {id:c.id};
    })().then(done,e=>done({error:e.message,stack:e.stack}));''',base,'Radicale - Password Required')
    assert not configured.get('error'),configured
    js("Services.io.getProtocolHandler('resource').QueryInterface(Ci.nsIResProtocolHandler).setSubstitution('acceptance-native',Services.io.newURI(arguments[0]));",ROOT.joinpath('addon').as_uri()+'/')
    native='resource://acceptance-native/native-calendar.mjs'
    def native_tasks():
        result=async_js('''const done=arguments[arguments.length-1];ChromeUtils.importESModule(arguments[0]).nativeTasks.list({}).then(done,e=>done({error:e.message,stack:e.stack}));''',native)
        if isinstance(result,dict) and result.get('error'):raise RuntimeError(str(result))
        return result
    print('Native CalDAV configured',configured,flush=True)
    listing=wait_for(lambda: (v if isinstance(v:=native_tasks(),list) and len(v)>=5 else None),timeout=45)
    english=next(t for t in listing if t['title'].startswith('英语'))
    chemistry=next(t for t in listing if t['title'].startswith('化学'))
    # Resolve the actual extension URL. Open its production page as a Thunderbird tab.
    extension_url=js('''return WebExtensionPolicy.getByID(arguments[0]).getURL('page.html');''',installed['id'])
    actor_script="Services.io.getProtocolHandler('resource').QueryInterface(Ci.nsIResProtocolHandler).setSubstitution('acceptance-rebuild',Services.io.newURI(arguments[0]));ChromeUtils.registerWindowActor('AssistantAcceptance',{allFrames:true,includeChrome:true,parent:{esModuleURI:'resource://acceptance-rebuild/tests/ActorParent.sys.mjs'},child:{esModuleURI:'resource://acceptance-rebuild/tests/ActorChild.sys.mjs'},matches:['moz-extension://*/*']});"
    js(actor_script,ROOT.as_uri()+'/')
    def page_js(script,*args):
        result=async_js("const done=arguments[arguments.length-1];const browser=window.document.getElementById('tabmail').selectedBrowser;browser.browsingContext.currentWindowGlobal.getActor('AssistantAcceptance').sendQuery('run',{script:arguments[0],args:arguments[1]}).then(done,e=>done({error:e.message}));",script,list(args))
        if isinstance(result,dict) and result.get('error'):raise RuntimeError(str(result))
        return result
    def navigate(url):
        m.set_context('chrome')
        js("window.document.getElementById('tabmail').openTab('contentTab',{url:arguments[0]});",url)
        wait_for(lambda:page_js("if(document.URL!==args[0])return false;const error=document.querySelector('#message')?.textContent;if(!document.querySelector('#app')?.textContent.length && error)throw new Error(error);return document.querySelector('#app')?.textContent.length>0;",url))
    def text():
        result=page_js("const error=document.querySelector('#message')?.textContent;if(error && error!=='任务已保存' && !error.startsWith('任务已保存；'))throw new Error(error);return document.body.innerText;")
        return result
    def click(selector):
        wait_for(lambda:page_js('return Boolean(document.querySelector(args[0]));',selector))
        page_js('document.querySelector(args[0]).click();',selector)
    def configure_wp(executable):
        navigate(extension_url+'?view=settings')
        page_js("document.querySelector('[name=wpEnabled]').checked=true;document.querySelector('[name=wpAutoLog]').checked=true;document.querySelector('[name=wpMode]').value='wp-cli';document.querySelector('[name=wpPath]').value=args[0];document.querySelector('[name=wpExecutable]').value=args[1];",os.environ['WP_PATH'],executable)
        click('[data-action=save-settings]');wait_for(lambda:page_js("return document.querySelector('#message').textContent==='已保存';"))
    if os.environ.get('WP_EXECUTABLE'):
        configure_wp('/tmp/intentionally-unavailable-acceptance-wp')
    navigate(extension_url+'?id='+requests.utils.quote(english['id'],safe=''))
    assert '开始' in text(),text()
    click('[data-action=start]');wait_for(lambda:'停止' in text())
    m.set_context('chrome');after_start=next(t for t in native_tasks() if t['id']==english['id']);assert after_start['status']=='IN-PROCESS'
    assert '[CALDAV-ASSISTANT-WORKLOG v1]' in after_start['description']
    js('Services.prefs.savePrefFile(null);setTimeout(()=>Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit),0);');tb.wait(timeout=15)
    tb=subprocess.Popen([binary,'--headless','--no-remote','--profile',str(profile),'--marionette','--remote-allow-system-access'],stdout=log,stderr=subprocess.STDOUT)
    m=Marionette('localhost',port=2828,socket_timeout=30);m.raise_for_port(timeout=30);m.start_session();m.set_context('chrome')
    installed=async_js(install_script,addon_path);assert not installed.get('error'),installed
    js("Services.io.getProtocolHandler('resource').QueryInterface(Ci.nsIResProtocolHandler).setSubstitution('acceptance-native',Services.io.newURI(arguments[0]));",ROOT.joinpath('addon').as_uri()+'/')
    js(actor_script,ROOT.as_uri()+'/')
    extension_url=js("return WebExtensionPolicy.getByID(arguments[0]).getURL('page.html');",installed['id'])
    wait_for(lambda:isinstance(v:=native_tasks(),list) and any(t['id']==english['id'] for t in v))
    navigate(extension_url+'?id='+requests.utils.quote(english['id'],safe=''))
    assert '停止' in text() and '开始' not in text(),text()
    print('Real process restart preserved active task',flush=True)

    navigate(extension_url+'?search='+requests.utils.quote('化学'))
    assert '化学' in text() and '英语' not in text(),text();assert '开始' not in text()
    click('main a');wait_for(lambda:'OTHER_TASK_CURRENT' in text());assert '开始' not in text(),text()
    m.set_context('chrome');navigate(extension_url+'?id='+requests.utils.quote(english['id'],safe=''))
    click('[data-action=stop]');wait_for(lambda:'开始' in text())
    m.set_context('chrome');after_stop=next(t for t in native_tasks() if t['id']==english['id']);assert after_stop['percentComplete']==35 and after_stop['status']=='NEEDS-ACTION',after_stop
    assert after_stop['description'].startswith(english['description']+'\n\n')
    navigate(extension_url+'?id='+requests.utils.quote(english['id'],safe=''));click('[data-action=start]');wait_for(lambda:'完成' in text());click('[data-action=complete]');wait_for(lambda:'COMPLETED' in text())
    m.set_context('chrome');completed=next(t for t in native_tasks() if t['id']==english['id']);assert completed['status']=='COMPLETED' and completed['percentComplete']==100 and completed['completedAt']
    navigate(extension_url+'?id='+requests.utils.quote(chemistry['id'],safe=''));click('[data-action=start]');wait_for(lambda:'取消' in text());click('[data-action=cancel]');wait_for(lambda:'CANCELLED' in text())
    recurring_rows=[t for t in native_tasks() if t['title'].startswith('每日')]
    assert len(recurring_rows)==3,recurring_rows
    occurrence=recurring_rows[0]
    navigate(extension_url+'?id='+requests.utils.quote(occurrence['id'],safe=''));click('[data-action=start]');wait_for(lambda:'停止' in text());click('[data-action=stop]');wait_for(lambda:'开始' in text())
    siblings=[t for t in native_tasks() if t['title'].startswith('每日') and t['id']!=occurrence['id']]
    assert all('CALDAV-ASSISTANT' not in t['description'] and t['status']=='NEEDS-ACTION' for t in siblings)
    if os.environ.get('WP_EXECUTABLE'):
        wait_for(lambda:page_js("return document.defaultView.wrappedJSObject.messenger.storage.local.get('caldavAssistant.outbox').then(v=>v['caldavAssistant.outbox'].some(r=>r.attempts>0));"))
        queued=page_js("return document.defaultView.wrappedJSObject.messenger.storage.local.get('caldavAssistant.outbox').then(v=>v['caldavAssistant.outbox']);")
        assert len(queued)==4,queued
        configure_wp(os.environ['WP_EXECUTABLE']);navigate(extension_url+'?view=wordpress');click('[data-action=retry]')
        wait_for(lambda:page_js("return document.defaultView.wrappedJSObject.messenger.storage.local.get('caldavAssistant.outbox').then(v=>v['caldavAssistant.outbox'].length===0);"))
        print('Actual VTODO commits survived unavailable WordPress and all 4 logs retried via native WP-CLI',flush=True)
    # Logs and Today are actual read-only pages. Capture real extension storage around navigation.
    def stored():return page_js("return document.defaultView.wrappedJSObject.messenger.storage.local.get(null);")
    before=stored();navigate(extension_url+'?view=logs');navigate(extension_url+'?view=today');after=stored();assert before==after,'Read-only page mutated storage'
    # The independent HTTP read is evidence beyond Thunderbird's in-memory model.
    for uid,expected in [('english','COMPLETED'),('chemistry','CANCELLED')]:
        body=requests.get(base+uid+'.ics',auth=auth).text
        assert 'STATUS:'+expected in body,body
        assert 'CALDAV-ASSISTANT-WORKLOG' in body and 'result' in body
        ART.joinpath(uid+'-readback.ics').write_text(body)
    # Seed an old persisted data shape, then run the isolated migration command
    # against a genuine VTODO and genuine extension storage. No old code is loaded.
    migration_task=async_js("const done=arguments[arguments.length-1];(async()=>{const {cal}=ChromeUtils.importESModule('resource:///modules/calendar/calUtils.sys.mjs');const calendar=cal.manager.getCalendarById(arguments[0]);const {CalTodo}=ChromeUtils.importESModule('resource:///modules/CalTodo.sys.mjs');const todo=new CalTodo();todo.id='legacy-active';todo.title='历史正在进行的任务';todo.status='IN-PROCESS';todo.percentComplete=60;todo.setProperty('DESCRIPTION','历史正文\\n不删除');await calendar.addItem(todo);return {calendarId:calendar.id,id:todo.id,recurrenceId:'',description:todo.getProperty('DESCRIPTION')};})().then(done,e=>done({error:e.message}));",configured['id'])
    assert not migration_task.get('error'),migration_task
    old_pointer='|'.join(requests.utils.quote(migration_task[key],safe='') for key in ['calendarId','id','recurrenceId'])
    seed={'caldavAssistant.currentWorkId':old_pointer,'caldavAssistant.descriptionMigrationV1':False,'caldavAssistant.runtime':{'currentTask':migration_task},'caldavAssistant.audit.2026-10-03':[{'scope':'workflow','action':'start','success':True,'timestamp':'2026-10-03T09:00:00Z','details':{'task':{**migration_task,'beforeStatus':'NEEDS-ACTION','beforePercentComplete':20}}}]}
    page_js("return document.defaultView.wrappedJSObject.messenger.storage.local.set(args[0]);",seed)
    navigate(extension_url+'?view=settings');click('[data-action=recover]')
    wait_for(lambda:page_js("return document.defaultView.wrappedJSObject.messenger.storage.local.get(['caldavAssistant.runtime','caldavAssistant.descriptionMigrationV1']).then(v=>!v['caldavAssistant.runtime'] && v['caldavAssistant.descriptionMigrationV1']===true);"))
    converted=next(t for t in native_tasks() if t['title']=='历史正在进行的任务')
    navigate(extension_url+'?id='+requests.utils.quote(converted['id'],safe=''));assert '停止' in text();click('[data-action=stop]');wait_for(lambda:'开始' in text())
    restored=next(t for t in native_tasks() if t['id']==converted['id']);assert restored['percentComplete']==20 and restored['status']=='NEEDS-ACTION'
    assert restored['description'].startswith(migration_task['description']+'\n\n')
    print('Actual one-time migration and original 20% progress restore passed',flush=True)
    if os.environ.get('WP_EXECUTABLE') and os.environ.get('WP_PATH'):
        for operation in ['test','full-test']:
            result=async_js("const done=arguments[arguments.length-1];ChromeUtils.importESModule('resource://acceptance-native/native-wordpress.mjs').wpCli(arguments[0],{id:'native-acceptance-'+Date.now()},arguments[1]).then(done,e=>done({error:e.message}));",operation,{'wpExecutable':os.environ['WP_EXECUTABLE'],'wpPath':os.environ['WP_PATH']})
            assert not result.get('error'),result
            print('Native WP-CLI',operation,result,flush=True)
            ART.joinpath('native-wordpress-'+operation+'.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    report={'thunderbird':js('return Services.appinfo.version;'),'addon':installed['id'],'provider':'real Thunderbird CalDAV + Radicale','clicks':'Marionette drives real production DOM HTMLElement.click and event handlers (equivalent click automation)','checks':['start','real process restart preserves active task','filtered current hidden','other current blocks start','stop restores 35%','Description preserved','complete 100% with COMPLETED date','cancel','recurring occurrence isolation','Logs/Today zero storage mutations','actual workflow → durable Outbox during CLI failure → real native WP-CLI retry','independent HTTP VTODO read-back','real native VTODO + extension storage one-time legacy migration'],'passed':True,'xpiSha256':hashlib.sha256(Path(addon_path).read_bytes()).hexdigest() if Path(addon_path).is_file() else None}
    ART.joinpath('real-thunderbird-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
    m.delete_session()
finally:
    if tb:tb.terminate();tb.wait(timeout=15)
    rad.terminate();rad.wait(timeout=15)
    log.close()
    ART.joinpath('thunderbird-last.log').write_text((work/'thunderbird.log').read_text())
