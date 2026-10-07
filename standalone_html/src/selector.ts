import { createWork, type Action } from './work.js';
import { AssistantActionPlan as Core } from './generated-core.js';
import { createTransport, CalDAVError } from './transport.js';
import { createCalDAV } from './caldav.js';
import { projectTasks, selectTasks, readTaskDetails, type Task } from './tasks.js';
const form = document.querySelector<HTMLFormElement>('#connect')!;
const notice = document.querySelector<HTMLElement>('#notice')!;
const list = document.querySelector<HTMLElement>('#task-list')!;
const query = document.querySelector<HTMLInputElement>('#query')!;
let tasks: readonly Task[] = [];
let selectedTask: Task | null = null;
let currentWorkId: string | null = null;
let work: ReturnType<typeof createWork> | null = null;
let working = false;
const workNotice = document.querySelector<HTMLElement>('#current-work')!;
const actions = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-action]'));
function updateActions() {
  const selectedKey = selectedTask ? Core.identity({calendarId:selectedTask.calendarUrl,id:selectedTask.uid,recurrenceId:selectedTask.recurrenceId ?? ''}) : null;
  workNotice.textContent = currentWorkId === null ? '当前没有工作。' : '已有当前工作：请选择该任务进行停止、完成或取消。';
  for (const button of actions) button.disabled = working || !work || !selectedTask ||
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
  if (working) return;
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
    }});
    updateActions();
    transport = connection; tasks = Object.freeze(loaded); render(); notice.textContent = `已读取 ${tasks.length} 个任务。`;
  } catch (error) {
    if (generation !== loadGeneration) return;
    tasks = []; list.replaceChildren();
    notice.textContent = error instanceof CalDAVError && error.code === 'Permission'
      ? '认证失败，请检查用户名和密码。' : error instanceof CalDAVError && error.code === 'Validation'
      ? '服务器数据无法完整验证，未显示部分结果。' : '连接失败，请检查地址、证书信任和服务器跨域设置。';
  }
});
query.addEventListener('input', render);

updateActions();
