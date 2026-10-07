import { createTransport, CalDAVError } from './transport.js';
import { createCalDAV } from './caldav.js';
import { projectTasks, selectTasks, type Task } from './tasks.js';
const form = document.querySelector<HTMLFormElement>('#connect')!;
const notice = document.querySelector<HTMLElement>('#notice')!;
const list = document.querySelector<HTMLElement>('#task-list')!;
const query = document.querySelector<HTMLInputElement>('#query')!;
let tasks: readonly Task[] = [];
let loadGeneration = 0;
function render() {
  list.replaceChildren();
  for (const task of selectTasks(tasks, query.value)) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'task-item';
    button.textContent = task.title || '（无标题）';
    // Selection publishes only identity, never task/workflow state.
    button.addEventListener('click', () => {
      document.dispatchEvent(new CustomEvent('task-selected', { detail: task.taskId }));
      notice.textContent = `已选择：${task.title}。工作页面接入尚在迁移中。`;
    });
    list.append(button);
  }
  if (!list.childNodes.length) list.textContent = '没有匹配的未完成任务。';
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const generation = ++loadGeneration;
  tasks = []; list.replaceChildren(); notice.textContent = '正在连接并读取任务……';
  const data = new FormData(form);
  try {
    const baseUrl = String(data.get('url'));
    const username = String(data.get('username'));
    const password = String(data.get('password'));
    if (username.includes(':')) throw new CalDAVError('Validation');
    const bytes = new TextEncoder().encode(`${username}:${password}`);
    const authorization = 'Basic ' + btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(''));
    const client = createCalDAV(createTransport({ baseUrl, authorization, fetch: fetch.bind(globalThis) }), baseUrl,
      text => new DOMParser().parseFromString(text, 'application/xml'));
    const calendars = await client.discover();
    const loaded: Task[] = [];
    for (const calendar of calendars.filter(item => !item.components.length || item.components.includes('VTODO'))) {
      for (const resource of await client.tasks(calendar)) loaded.push(...projectTasks(calendar.url, resource));
    }
    if (new Set(loaded.map(task => task.taskId)).size !== loaded.length) throw new CalDAVError('Validation');
    if (generation !== loadGeneration) return;
    tasks = Object.freeze(loaded); render(); notice.textContent = `已读取 ${tasks.length} 个任务。`;
  } catch (error) {
    if (generation !== loadGeneration) return;
    tasks = []; list.replaceChildren();
    notice.textContent = error instanceof CalDAVError && error.code === 'Permission'
      ? '认证失败，请检查用户名和密码。' : error instanceof CalDAVError && error.code === 'Validation'
      ? '服务器数据无法完整验证，未显示部分结果。' : '连接失败，请检查地址、证书信任和服务器跨域设置。';
  }
});
query.addEventListener('input', render);
