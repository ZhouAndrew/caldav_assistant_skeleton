import { createTransport, CalDAVError } from './transport.js';
import { createCalDAV } from './caldav.js';
import { projectTasks, selectTasks, readTaskDetails, type Task } from './tasks.js';
const form = document.querySelector<HTMLFormElement>('#connect')!;
const notice = document.querySelector<HTMLElement>('#notice')!;
const list = document.querySelector<HTMLElement>('#task-list')!;
const query = document.querySelector<HTMLInputElement>('#query')!;
let tasks: readonly Task[] = [];
let loadGeneration = 0;
let selectionGeneration = 0;
let transport: ReturnType<typeof createTransport> | null = null;
const details = document.querySelector<HTMLElement>('#task-details')!;
async function showDetails(taskId: string) {
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
    notice.textContent = '已从服务器重新读取任务详情。工作操作尚未接入。';
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
  const generation = ++loadGeneration;
  ++selectionGeneration; transport = null; details.replaceChildren();
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
