const $ = id => document.getElementById(id);
let token = null;
let snapshot = null;

function say(message, error = false) {
  const node = $('notice');
  node.textContent = message;
  node.hidden = !message;
  node.classList.toggle('error', error);
}
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function when(value) {
  if (!value) return '未安排时间';
  // ISO date-only values stay dates in the user's locale; do not convert via UTC.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString([], {dateStyle: 'short', timeStyle: 'short'});
}
async function request(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}
async function post(path, payload) {
  if (!token) token = (await request('/api/token')).token;
  return request(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Assistant-Token': token}, body: JSON.stringify(payload)});
}
async function perform(payload) {
  if (payload.action === 'complete' && !confirm('确定完成这项任务？')) return;
  if (payload.action === 'start' || payload.action === 'resume') {
    const input = prompt('分配工作时长（分钟，可留空）', '');
    if (input === null) return;
    if (input.trim()) {
      const minutes = Number(input);
      if (!Number.isInteger(minutes) || minutes < 1 || minutes > 1440) { say('请输入 1 至 1440 分钟。', true); return; }
      payload.minutes = minutes;
    }
  }
  try {
    say('正在执行…');
    const result = await post('/api/task/action', payload);
    if (await refresh(true)) say(result.warning || result.message || '已完成', Boolean(result.warning));
  } catch (error) { say(error.message, true); }
}
function button(label, action, id, secondary = false) {
  const node = el('button', label, secondary ? 'secondary' : '');
  node.type = 'button';
  node.addEventListener('click', () => perform({action, id}));
  return node;
}
function addActions(target, task) {
  if (!task || !task.id) return;
  const actions = el('div', undefined, 'actions');
  if (snapshot.current_work_verified) {
    if (snapshot.current?.id === task.id) actions.append(button('暂停', 'pause', task.id, true));
    else if (snapshot.paused_ids.includes(task.id)) actions.append(button('继续', 'resume', task.id));
    else actions.append(button('开始', 'start', task.id));
  }
  actions.append(button('完成', 'complete', task.id, true));
  target.append(actions);
}
function row(item, isTask = false) {
  const outer = el('div', undefined, 'row');
  const body = el('div', undefined, 'row-body');
  body.append(el('strong', item.summary || '未命名'));
  const time = item.when || item.due || item.start;
  body.append(el('span', `${item.kind === 'event' ? '日程' : '任务'} · ${when(time)}`, 'meta'));
  outer.append(body);
  if (isTask) {
    const actions = el('div', undefined, 'actions');
    const edit = el('button', '编辑', 'secondary'); edit.type = 'button';
    edit.addEventListener('click', () => {
      $('edit-id').value = item.id;
      $('edit-summary').value = item.summary;
      $('edit-due').value = item.due?.slice(0, 10) || '';
      $('edit-dialog').dataset.originalSummary = item.summary;
      $('edit-dialog').dataset.originalDue = $('edit-due').value;
      $('edit-dialog').showModal();
    });
    actions.append(edit); addActions(actions, item); outer.append(actions);
  }
  return outer;
}
function render(data) {
  snapshot = data;
  $('current-actions').replaceChildren();
  if (!data.current_work_verified) {
    $('current-title').textContent = '正在核对当前任务';
    $('work-info').textContent = '后台尚未确认当前工作状态。';
  } else {
    $('current-title').textContent = data.current?.summary || '现在没有正在做的任务';
    const work = data.work;
    $('work-info').textContent = work?.state === 'scheduled' ? `工作时长到 ${when(work.deadline)}` : work?.state === 'expired' ? '分配的工作时间已到，任务仍在进行。' : '从下方选择任务开始。';
    if (data.current) addActions($('current-actions'), data.current);
  }
  const upcoming = data.upcoming.filter(Boolean);
  $('upcoming').replaceChildren(...(upcoming.length ? upcoming.map(item => row(item)) : [el('p', '未来 7 天暂无已安排的项目。', 'empty')]));
  const rec = $('recommendation'); rec.replaceChildren();
  if (data.recommended) { rec.append(el('strong', data.recommended.summary), el('p', `截止：${when(data.recommended.due)}`, 'meta')); addActions(rec, data.recommended); }
  else rec.append(el('p', '目前没有推荐的任务。', 'empty'));
  const tasks = data.tasks.filter(Boolean);
  $('task-count').textContent = `${tasks.length} 项未完成`;
  $('task-list').replaceChildren(...(tasks.length ? tasks.map(item => row(item, true)) : [el('p', '还没有未完成任务。', 'empty')]));
  if (data.snapshot) say('显示后台最近核验的日程快照；编辑操作仍会提交给 CalDAV。');
  else say('');
}
async function refresh(live = false) {
  try { render(await request(live ? '/api/snapshot?live=1' : '/api/snapshot')); return true; }
  catch (error) { say(error.message, true); $('current-title').textContent = '暂时无法读取'; $('work-info').textContent = '请检查后台和 CalDAV 连接，然后刷新。'; $('upcoming').replaceChildren(); $('recommendation').replaceChildren(); $('task-list').replaceChildren(); }
  return false;
}
$('refresh').addEventListener('click', () => refresh(true));
$('edit-cancel').addEventListener('click', () => $('edit-dialog').close());
$('create-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await post('/api/task/create', {summary: $('new-summary').value, due: $('new-due').value}); $('create-form').reset(); if (await refresh(true)) say('任务已添加'); }
  catch (error) { say(error.message, true); }
});
$('edit-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const change = {id: $('edit-id').value};
    if ($('edit-summary').value !== $('edit-dialog').dataset.originalSummary) change.summary = $('edit-summary').value;
    if ($('edit-due').value !== $('edit-dialog').dataset.originalDue) change.due = $('edit-due').value;
    if (Object.keys(change).length === 1) { $('edit-dialog').close(); return; }
    await post('/api/task/edit', change);
    $('edit-dialog').close();
    if (await refresh(true)) say('任务已保存');
  }
  catch (error) { say(error.message, true); }
});
refresh();
