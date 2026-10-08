import { createWork, type Action, type PendingAction } from './work.js';
import { AssistantActionPlan as Core } from './generated-core.js';
import { createTransport, CalDAVError } from './transport.js';
import { createCalDAV } from './caldav.js';
import { projectTasks, selectTasks, readTaskDetails, type Task } from './tasks.js';
import { createWordPress, createCaptureOutbox, openCaptureStore, WordPressError, type Capture, type CaptureFile, type CaptureStore, type WordPressConfig } from './wordpress.js';
const form = document.querySelector<HTMLFormElement>('#connect')!;
const notice = document.querySelector<HTMLElement>('#notice')!;
const list = document.querySelector<HTMLElement>('#task-list')!;
const query = document.querySelector<HTMLInputElement>('#query')!;
let tasks: readonly Task[] = [];
let selectedTask: Task | null = null;
let currentWorkId: string | null = null;
let work: ReturnType<typeof createWork> | null = null;
let working = false;
let recoveryRequired = false;
let connecting = false;
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
  } catch {
    recoveryRequired = true;
    notice.textContent = '操作未确认成功，请重新连接读取服务器状态；不要重复提交。';
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
    const loaded: Task[] = [];
    for (const calendar of calendars.filter(item => !item.components.length || item.components.includes('VTODO'))) {
      for (const resource of await client.tasks(calendar)) loaded.push(...projectTasks(calendar.url, resource));
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
    transport = connection; tasks = Object.freeze(loaded); render(); notice.textContent = `已读取 ${tasks.length} 个任务。`;
  } catch (error) {
    if (generation !== loadGeneration) return;
    tasks = []; list.replaceChildren(); work = null; transport = null; selectedTask = null; updateActions();
    notice.textContent = error instanceof CalDAVError && error.code === 'Permission'
      ? '认证失败，请检查用户名和密码。' : error instanceof CalDAVError && error.code === 'Validation'
      ? '服务器数据无法完整验证，未显示部分结果。' : error instanceof CalDAVError && error.code === 'Conflict'
      ? '上次操作结果与服务器不一致，已保留恢复记录并停用操作，请核对服务器数据。' : '连接失败，请检查地址、证书信任和服务器跨域设置。';
  } finally { connecting = false; }
});
query.addEventListener('input', render);

updateActions();

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
      if(!wordpress) {await showOutbox('已持久保存；');return;}
      const result=await captureOutbox.flush(wordpress);
      captureResult.textContent=result.pending?`已持久保存，仍有 ${result.pending} 项等待补写。`:'✓ 已追加并回读验证。';
      if(result.sent) await refreshPost();
    } catch(error) {
      await showOutbox('追加暂未完成；Task 操作不受影响。');
    }
  });
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
