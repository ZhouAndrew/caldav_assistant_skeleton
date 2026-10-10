import { createWork, type Action, type PendingAction } from './work.js';
import { AssistantActionPlan as Core } from './generated-core.js';
import { createTransport, CalDAVError } from './transport.js';
import { createCalDAV } from './caldav.js';
import { projectTasks, selectTasks, readTaskDetails, type Task } from './tasks.js';
import { createEventWriter, occursOn, projectEvents, propertyDay, type CalendarEvent } from './events.js';
import { createWordPress, createCaptureOutbox, openCaptureStore, WordPressError, type Capture, type CaptureFile, type CaptureStore, type WordPressConfig } from './wordpress.js';
import { filterAudit, localDateKey, memoryAuditStore, openAuditStore, readableAudit, type AuditRecord, type AuditScope } from './audit.js';
const auditStorePromise=openAuditStore().catch(()=>memoryAuditStore());
async function audit(scope:AuditScope,action:string,success:boolean,summary:string,details?:unknown) {
  const timestamp=new Date().toISOString();
  try { await (await auditStorePromise).put(Object.freeze({id:crypto.randomUUID(),timestamp,localDate:localDateKey(timestamp),scope,action,success,summary,details})); }
  catch { /* Audit must never block either independent lane. */ }
}
const form = document.querySelector<HTMLFormElement>('#connect')!;
const notice = document.querySelector<HTMLElement>('#notice')!;
const list = document.querySelector<HTMLElement>('#task-list')!;
const query = document.querySelector<HTMLInputElement>('#query')!;
let tasks: readonly Task[] = [];
let events: readonly CalendarEvent[] = [];
let selectedEvent:CalendarEvent|null=null;let eventWriter:ReturnType<typeof createEventWriter>|null=null;
let selectedTask: Task | null = null;
let currentWorkId: string | null = null;
let work: ReturnType<typeof createWork> | null = null;
let working = false;
let recoveryRequired = false;
let connecting = false;
let calendarSummary:readonly {url:string;name:string;components:readonly string[]}[]=[];
const workNotice = document.querySelector<HTMLElement>('#current-work')!;
const actions = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-action]'));
function updateActions() {
  const selectedKey = selectedTask ? Core.identity({calendarId:selectedTask.calendarUrl,id:selectedTask.uid,recurrenceId:selectedTask.recurrenceId ?? ''}) : null;
  workNotice.textContent = currentWorkId === null ? '当前没有工作。' : '已有当前工作：请选择该任务进行停止、完成或取消。';
  for (const button of actions) button.disabled = recoveryRequired || working || !work || !selectedTask ||
    selectedTask.recurring || selectedTask.recurrenceId !== null || ['COMPLETED','CANCELLED'].includes(selectedTask.status) ||
    (button.dataset.action === 'start' ? currentWorkId !== null : selectedKey !== currentWorkId);
}
for (const button of actions) button.addEventListener('click', async () => {
  if (working || !selectedTask || !work) return;
  const selected = selectedTask;
  working = true; updateActions();
  notice.textContent = '正在写入并回读验证……';
  try {
    const receipt = await work.run(button.dataset.action as Action,selected,new Date().toISOString(),crypto.randomUUID());
    const fresh = readTaskDetails(selected.calendarUrl,receipt.resource,selected.taskId);
    tasks = tasks.map(task => task.taskId === fresh.task.taskId ? fresh.task : task);
    render(); await showDetails(selected.taskId);
    notice.textContent = '操作已写入并回读验证。';
    void audit('workflow',`task.${button.dataset.action}`,true,'Task 操作已写入并回读验证。',{taskId:selected.taskId,verified:receipt.verified});
  } catch {
    recoveryRequired = true;
    notice.textContent = '操作未确认成功，请重新连接读取服务器状态；不要重复提交。';
    void audit('workflow',`task.${button.dataset.action}`,false,'Task 操作结果未确认；需要重新连接恢复。',{taskId:selected.taskId});
  } finally { working = false; updateActions(); }
});
let loadGeneration = 0;
let selectionGeneration = 0;
let transport: ReturnType<typeof createTransport> | null = null;
const details = document.querySelector<HTMLElement>('#task-details')!;
async function showDetails(taskId: string) {
  if (working && selectedTask?.taskId !== taskId) return;
  selectedTask = null; updateActions();
  const task = tasks.find(item => item.taskId === taskId);
  const connection = transport;
  if (!task || !connection) return;
  const generation = ++selectionGeneration;
  details.replaceChildren(); notice.textContent = '正在重新读取所选任务……';
  try {
    const fresh = readTaskDetails(task.calendarUrl, await connection.read(task.resourceUrl), taskId);
    if (generation !== selectionGeneration) return;
    const title = document.createElement('h3'); title.textContent = fresh.task.title || '（无标题）';
    const status = document.createElement('p'); status.textContent = `状态：${fresh.task.status}`;
    const due = document.createElement('p'); due.textContent = `截止：${fresh.task.due ?? '未设置'}`;
    const description = document.createElement('pre'); description.textContent = fresh.description;
    details.replaceChildren(title, status, due, description);
    selectedTask = fresh.task; updateActions();
    notice.textContent = '已从服务器重新读取任务详情。';
  } catch {
    if (generation !== selectionGeneration) return;
    details.replaceChildren(); notice.textContent = '无法重新读取所选任务，请重新连接或选择。';
  }
}
document.addEventListener('task-selected', event => {
  const taskId: unknown = (event as CustomEvent<unknown>).detail;
  if (typeof taskId === 'string') void showDetails(taskId);
});
function render() {
  list.replaceChildren();
  for (const task of selectTasks(tasks, query.value)) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'task-item';
    button.textContent = task.title || '（无标题）';
    // Selection publishes only identity, never task/workflow state.
    button.addEventListener('click', () => {
      document.dispatchEvent(new CustomEvent('task-selected', { detail: task.taskId }));

    });
    list.append(button);
  }
  if (!list.childNodes.length) list.textContent = '没有匹配的未完成任务。';
}
function renderToday() {
  const root=document.querySelector<HTMLElement>('#today-items')!;root.replaceChildren();
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const part=(name:string)=>parts.find(item=>item.type===name)?.value;const day=`${part('year')}-${part('month')}-${part('day')}`;
  const todayTasks=tasks.filter(task=>propertyDay(task.due)===day);
  const todayEvents=events.filter(event=>occursOn(event,day));
  if(!todayTasks.length&&!todayEvents.length){root.textContent='今天没有 Task 或 Event。';return;}
  const table=document.createElement('table');const body=document.createElement('tbody');
  for(const item of todayTasks.map(task=>({type:'Task',time:task.due??'',title:task.title,state:task.status,event:null as CalendarEvent|null}))) {
    const row=document.createElement('tr');for(const value of [item.type,item.time,item.title||'（无标题）',item.state]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}body.append(row);
  }
  for(const event of todayEvents) {
    const row=document.createElement('tr');for(const value of ['Event',event.start,event.title||'（无标题）',event.location]){const cell=document.createElement('td');if(value===event.title){const button=document.createElement('button');button.type='button';button.textContent=value;button.addEventListener('click',()=>selectEvent(event));cell.append(button);}else cell.textContent=value;row.append(cell);}body.append(row);
  }
  table.append(body);root.append(table);
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (working || connecting) return;
  connecting = true;
  const generation = ++loadGeneration;
  ++selectionGeneration; transport = null; work = null; selectedTask = null; updateActions(); details.replaceChildren();
  tasks = []; list.replaceChildren(); notice.textContent = '正在连接并读取任务……';
  const data = new FormData(form);
  try {
    const baseUrl = String(data.get('url'));
    const username = String(data.get('username'));
    const password = String(data.get('password'));
    if (username.includes(':')) throw new CalDAVError('Validation');
    const bytes = new TextEncoder().encode(`${username}:${password}`);
    const authorization = 'Basic ' + btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(''));
    const connection = createTransport({ baseUrl, authorization, fetch: fetch.bind(globalThis) });
    const client = createCalDAV(connection, baseUrl,
      text => new DOMParser().parseFromString(text, 'application/xml'));
    const calendars = await client.discover();
    calendarSummary=Object.freeze(calendars.map(item=>Object.freeze({url:item.url,name:item.name,components:item.components})));
    const loaded: Task[] = [];const loadedEvents:CalendarEvent[]=[];
    for (const calendar of calendars.filter(item => !item.components.length || item.components.includes('VTODO'))) {
      for (const resource of await client.tasks(calendar)) loaded.push(...projectTasks(calendar.url, resource));
    }
    for (const calendar of calendars.filter(item => !item.components.length || item.components.includes('VEVENT'))) {
      for (const resource of await client.events(calendar)) loadedEvents.push(...projectEvents(calendar.url, resource));
    }
    if (new Set(loaded.map(task => task.taskId)).size !== loaded.length) throw new CalDAVError('Validation');
    if (generation !== loadGeneration) return;
    const storageKey = `caldav-assistant.currentWorkId:${new URL(baseUrl).origin}:${username}`;
    currentWorkId = localStorage.getItem(storageKey);
    Core.parseIdentity(currentWorkId);
    work = createWork(connection,{read:()=>currentWorkId,publish:value=>{
      if (value === null) localStorage.removeItem(storageKey); else localStorage.setItem(storageKey,value);
      currentWorkId = value;
    }},{
      read:()=>{const value=localStorage.getItem(storageKey+':pending'); return value === null ? null : JSON.parse(value) as PendingAction;},
      save:value=>localStorage.setItem(storageKey+':pending',JSON.stringify(value)),
      clear:()=>localStorage.removeItem(storageKey+':pending'),
    });
    await work.recover();
    recoveryRequired = false;
    updateActions();
    transport = connection;eventWriter=createEventWriter(connection); tasks = Object.freeze(loaded);events=Object.freeze(loadedEvents);render();renderToday(); notice.textContent = `已读取 ${tasks.length} 个任务、${events.length} 个事件。`;
    void audit('connection','caldav.discover',true,`已发现 ${calendars.length} 个日历，读取 ${tasks.length} 个任务、${events.length} 个事件。`,{calendars:calendarSummary});
  } catch (error) {
    if (generation !== loadGeneration) return;
    tasks = [];events=[];selectedEvent=null;eventWriter=null;document.querySelector<HTMLElement>('#event-editor')!.hidden=true; list.replaceChildren();renderToday(); work = null; transport = null; selectedTask = null; updateActions();
    notice.textContent = error instanceof CalDAVError && error.code === 'Permission'
      ? '认证失败，请检查用户名和密码。' : error instanceof CalDAVError && error.code === 'Validation'
      ? '服务器数据无法完整验证，未显示部分结果。' : error instanceof CalDAVError && error.code === 'Conflict'
      ? '上次操作结果与服务器不一致，已保留恢复记录并停用操作，请核对服务器数据。' : '连接失败，请检查地址、证书信任和服务器跨域设置。';
    calendarSummary=[];void audit('connection','caldav.discover',false,notice.textContent);
  } finally { connecting = false; }
});
query.addEventListener('input', render);

updateActions();

const eventEditor=document.querySelector<HTMLElement>('#event-editor')!;const eventForm=document.querySelector<HTMLFormElement>('#event-form')!;const eventResult=document.querySelector<HTMLElement>('#event-result')!;
function selectEvent(event:CalendarEvent) {
  selectedEvent=event;(eventForm.elements.namedItem('title') as HTMLInputElement).value=event.title;(eventForm.elements.namedItem('location') as HTMLInputElement).value=event.location;
  const start=eventForm.elements.namedItem('start') as HTMLInputElement;const end=eventForm.elements.namedItem('end') as HTMLInputElement;
  start.type=event.allDay?'date':'datetime-local';end.type=event.allDay?'date':'datetime-local';start.value=event.editStart;end.value=event.editEnd;
  document.querySelector<HTMLElement>('#event-end-label')!.hidden=event.end===null;end.required=event.end!==null;
  document.querySelector<HTMLElement>('#event-time-note')!.textContent=event.allDay?'全天 Event：结束日期按 CalDAV 规则为不包含当天。':'保持原 Event 的 TZID；这里只修改该时区内的本地时间。';
  eventEditor.hidden=false;eventResult.textContent=event.recurrenceId!==null?'重复实例暂不允许修改。':'';
}
document.querySelector<HTMLButtonElement>('#event-cancel')!.addEventListener('click',()=>{selectedEvent=null;eventEditor.hidden=true;});
eventForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!selectedEvent||!eventWriter)return;const target=selectedEvent;const data=new FormData(eventForm);eventResult.textContent='正在写入并回读验证……';
  try {const receipt=await eventWriter.update(target,{title:String(data.get('title')),location:String(data.get('location')),start:String(data.get('start')),end:target.end===null?'':String(data.get('end'))});const fresh=projectEvents(target.calendarUrl,receipt.resource).find(item=>item.eventId===target.eventId);if(!fresh)throw new CalDAVError('Validation');events=Object.freeze(events.map(item=>item.eventId===fresh.eventId?fresh:item));selectedEvent=fresh;renderToday();eventResult.textContent='✓ Event 已写入并回读验证。';void audit('workflow','event.update',true,'Event 已写入并回读验证。',{eventId:target.eventId,verified:receipt.verified,start:fresh.editStart,end:fresh.editEnd});}
  catch {eventResult.textContent='Event 修改未确认成功，请重新连接读取服务器状态。';void audit('workflow','event.update',false,eventResult.textContent,{eventId:target.eventId});}
});

// WordPress is an independent output lane. None of its state participates in CalDAV actions.
const wordpressForm = document.querySelector<HTMLFormElement>('#wordpress-connect')!;
const capture = document.querySelector<HTMLTextAreaElement>('#quick-capture')!;
const captureResult = document.querySelector<HTMLElement>('#capture-result')!;
const preview = document.querySelector<HTMLIFrameElement>('#post-preview')!;
const previewStatus = document.querySelector<HTMLElement>('#preview-status')!;
const openPost = document.querySelector<HTMLAnchorElement>('#open-post')!;
let wordpress: ReturnType<typeof createWordPress> | null = null;
let captureTail = Promise.resolve();
let captureStore:CaptureStore;
try { captureStore=await openCaptureStore(); }
catch {
  // Storage availability must never stop the already initialized CalDAV lane.
  const memory=new Map<string,Capture>();
  captureStore={list:async()=>[...memory.values()],put:async value=>{memory.set(value.id,value);},delete:async id=>{memory.delete(id);}};
  captureResult.textContent='浏览器持久存储不可用；本次会话仍可捕获。';
}
const captureOutbox=createCaptureOutbox(captureStore);
async function showOutbox(prefix='') { const count=(await captureOutbox.list()).length;captureResult.textContent=prefix+(count?`待补写 ${count} 项。`:'Outbox 为空。'); }
function readWordPressConfig(): WordPressConfig | null {
  const saved = localStorage.getItem('caldav-assistant.wordpress');
  if (!saved) return null;
  try {
    const publicConfig = JSON.parse(saved) as {baseUrl?:unknown;username?:unknown};
    const password = sessionStorage.getItem('caldav-assistant.wordpress.password') ?? '';
    if (typeof publicConfig.baseUrl !== 'string' || typeof publicConfig.username !== 'string' || !password) return null;
    return {baseUrl:publicConfig.baseUrl,username:publicConfig.username,applicationPassword:password};
  } catch { return null; }
}
function connectWordPress(config: WordPressConfig) {
  wordpress = createWordPress({config,fetch:fetch.bind(globalThis)});
}
const savedWordPress = localStorage.getItem('caldav-assistant.wordpress');
if (savedWordPress) try {
  const value=JSON.parse(savedWordPress) as {baseUrl?:string;username?:string};
  if(value.baseUrl) (wordpressForm.elements.namedItem('url') as HTMLInputElement).value=value.baseUrl;
  if(value.username) (wordpressForm.elements.namedItem('username') as HTMLInputElement).value=value.username;
} catch { localStorage.removeItem('caldav-assistant.wordpress'); }
const initialWordPress=readWordPressConfig();if(initialWordPress) connectWordPress(initialWordPress);
wordpressForm.addEventListener('submit',event=>{
  event.preventDefault();const data=new FormData(wordpressForm);
  const config={baseUrl:String(data.get('url')),username:String(data.get('username')),applicationPassword:String(data.get('password'))};
  try {
    connectWordPress(config);
    localStorage.setItem('caldav-assistant.wordpress',JSON.stringify({baseUrl:config.baseUrl,username:config.username}));
    sessionStorage.setItem('caldav-assistant.wordpress.password',config.applicationPassword);
    previewStatus.textContent='WordPress 设置已保存；Application Password 仅保留到当前浏览器会话。';
    void retryCaptures();
  } catch { wordpress=null;previewStatus.textContent='WordPress URL 无效。'; }
});
async function refreshPost() {
  previewStatus.textContent='正在独立读取今天的 Post……';
  try {
    if(!wordpress) throw new WordPressError('Permission');
    const post=await wordpress.findDaily(new Date(),false);
    if(!post) { preview.hidden=true;openPost.hidden=true;previewStatus.textContent='今天尚无日志 Post。';return; }
    const url=new URL(post.link);if(!['http:','https:'].includes(url.protocol)) throw new WordPressError('Validation');
    openPost.href=url.href;openPost.hidden=false;preview.src=url.href;preview.hidden=false;previewStatus.textContent='完整 Post 已直接载入 iframe。';
  } catch(error) {
    preview.hidden=true;openPost.hidden=true;
    previewStatus.textContent=error instanceof WordPressError&&error.code==='Permission'?'请先填写 WordPress 设置。':'读取 Post 失败；Task 操作不受影响。';
  }
}
document.querySelector<HTMLButtonElement>('#refresh-post')!.addEventListener('click',()=>void refreshPost());
function filesFrom(data: DataTransfer | null): File[] {
  const files=Array.from(data?.files??[]);if(files.length) return files;
  return Array.from(data?.items??[]).filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter((item):item is File=>item!==null);
}
function appendCapture(content:string,files:readonly File[]) {
  captureTail=captureTail.then(async()=>{
    captureResult.textContent='正在追加……';
    try {
      const converted:CaptureFile[]=[];for(const file of files) converted.push({name:file.name||'clipboard.bin',type:file.type,bytes:await file.arrayBuffer()});
      await captureOutbox.enqueue({id:crypto.randomUUID(),at:new Date().toISOString(),content,files:converted});capture.value='';
      if(!wordpress) {await showOutbox('已持久保存；');void audit('wordpress','wordpress.capture',true,'日志已保存到 Outbox，等待 WordPress 设置。',{files:files.map(file=>file.name)});return;}
      const result=await captureOutbox.flush(wordpress);
      captureResult.textContent=result.pending?`已持久保存，仍有 ${result.pending} 项等待补写。`:'✓ 已追加并回读验证。';
      void audit('wordpress','wordpress.capture',true,result.pending?'日志已保存到 Outbox，等待补写。':'日志已追加并回读验证。',{pending:result.pending,files:files.map(file=>file.name)});
      if(result.sent) await refreshPost();
    } catch(error) {
      await showOutbox('追加暂未完成；Task 操作不受影响。');
      void audit('wordpress','wordpress.capture',false,'追加暂未完成；内容仍保留在 Outbox。',{files:files.map(file=>file.name)});
    }
  });
  return captureTail;
}
capture.addEventListener('paste',event=>{const files=filesFrom(event.clipboardData);const content=event.clipboardData?.getData('text/plain')??'';if(!files.length&&!content.trim())return;event.preventDefault();appendCapture(content,files);});
capture.addEventListener('dragover',event=>{if([...(event.dataTransfer?.types??[])].includes('Files'))event.preventDefault();});
capture.addEventListener('drop',event=>{const files=filesFrom(event.dataTransfer);if(!files.length)return;event.preventDefault();appendCapture('',files);});
async function retryCaptures() {
  if(!wordpress) {await showOutbox('请先填写 WordPress 设置；');return;}
  const result=await captureOutbox.flush(wordpress);captureResult.textContent=result.pending?`仍有 ${result.pending} 项等待补写。`:`✓ 已补写 ${result.sent} 项，Outbox 为空。`;if(result.sent)await refreshPost();
}
document.querySelector<HTMLButtonElement>('#retry-captures')!.addEventListener('click',()=>void retryCaptures());
void showOutbox();

// Record reuses the exact durable capture path used by Quick Capture.
const recordContent=document.querySelector<HTMLTextAreaElement>('#record-content')!;
const recordFiles=document.querySelector<HTMLInputElement>('#record-files')!;
const recordResult=document.querySelector<HTMLElement>('#record-result')!;
document.querySelector<HTMLButtonElement>('#record-submit')!.addEventListener('click',async()=>{
  const content=recordContent.value;const files=Array.from(recordFiles.files??[]);
  if(!content.trim()&&!files.length){recordResult.textContent='请输入日志内容或选择附件。';return;}
  recordResult.textContent='正在持久保存……';await appendCapture(content,files);
  const pending=(await captureOutbox.list()).length;recordContent.value='';recordFiles.value='';
  recordResult.textContent=pending?`日志已保存在 Outbox；待补写 ${pending} 项。`:'✓ 日志已追加并回读验证。';
});

// Logs expose the standalone audit store without depending on Thunderbird APIs.
const logRoot=document.querySelector<HTMLElement>('#log-items')!;const logStatus=document.querySelector<HTMLElement>('#log-status')!;
let auditRecords:readonly AuditRecord[]=[];
function visibleAudit(){return filterAudit(auditRecords,{scope:document.querySelector<HTMLSelectElement>('#log-scope')!.value,date:document.querySelector<HTMLInputElement>('#log-date')!.value,search:document.querySelector<HTMLInputElement>('#log-search')!.value});}
function renderAudit(){const items=[...visibleAudit()].reverse();logRoot.replaceChildren();if(!items.length){logRoot.textContent=auditRecords.length?'当前筛选没有匹配的日志。':'尚无操作日志。';return;}for(const record of items){const row=document.createElement('article');row.className='log-record';const head=document.createElement('div');head.className='log-head';for(const value of [new Date(record.timestamp).toLocaleTimeString(),record.scope,record.success?'✓ 成功':'✗ 失败']){const span=document.createElement('span');span.textContent=value;head.append(span);}const summary=document.createElement('p');summary.textContent=record.summary;const pre=document.createElement('pre');pre.textContent=JSON.stringify(record.details??{},null,2);row.append(head,summary,pre);logRoot.append(row);}}
async function loadAudit(){auditRecords=await (await auditStorePromise).list();renderAudit();}
for(const selector of ['#log-scope','#log-date','#log-search']) document.querySelector(selector)!.addEventListener(selector==='#log-search'?'input':'change',renderAudit);
document.querySelector<HTMLButtonElement>('#log-reload')!.addEventListener('click',()=>void loadAudit());
async function copyAudit(json:boolean){try{await navigator.clipboard.writeText(json?JSON.stringify(visibleAudit(),null,2):readableAudit(visibleAudit()));logStatus.textContent='✓ 已复制当前可见日志。';}catch{logStatus.textContent='浏览器拒绝剪贴板访问。';}}
document.querySelector<HTMLButtonElement>('#log-copy')!.addEventListener('click',()=>void copyAudit(false));document.querySelector<HTMLButtonElement>('#log-json')!.addEventListener('click',()=>void copyAudit(true));
document.querySelector<HTMLButtonElement>('#log-clear')!.addEventListener('click',async()=>{const date=document.querySelector<HTMLInputElement>('#log-date')!.value;if(!date){logStatus.textContent='请先选择要清空的日期。';return;}if(!confirm(`确认清空 ${date} 的操作日志？`))return;await (await auditStorePromise).clear(date);logStatus.textContent=`✓ 已清空 ${date} 的操作日志。`;await loadAudit();});
void loadAudit();

document.querySelector<HTMLButtonElement>('#connection-test')!.addEventListener('click',async()=>{
  const result=document.querySelector<HTMLElement>('#connection-result')!;
  if(!transport){result.textContent='请先连接 CalDAV。';return;}
  result.textContent=JSON.stringify({success:true,mode:'只读发现',calendars:calendarSummary,tasks:tasks.length,events:events.length},null,2);
  await audit('connection','caldav.quick-test',true,`只读连接测试通过：${calendarSummary.length} 个日历。`,{calendars:calendarSummary,tasks:tasks.length,events:events.length});await loadAudit();
});

addEventListener('hashchange',()=>{for(const link of Array.from(document.querySelectorAll<HTMLAnchorElement>('.tool-nav a')))link.classList.toggle('active',link.hash===(location.hash||'#work'));});
