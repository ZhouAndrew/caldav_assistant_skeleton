const HOST = "local.caldav_assistant_experimental";
const ATTACHMENT_CHUNK_BYTES = 256 * 1024;
const $ = (id) => document.getElementById(id);

let nativePort = null;
const nativeWaiters = [];
let diagnosticPort = null;
const diagnosticWaiters = [];
let integrationPort = null;
const integrationWaiters = [];
let currentSnapshot = {tasks: [], state: {current_task_id: null, paused_task_ids: []}, today: []};
let selectedTaskIdValue = "";
let taskRefreshTimer = null;
let logAutoRefreshTimer = null;
let actionBusy = false;
let activeTab = "work";
const EXPECTED_LOG_PATH = "~/.local/state/caldav-assistant/thunderbird/native-host.log";

function localInputNow() {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

function isoFromInput() {
  const raw = $("when").value;
  if (!raw) throw new Error("Please enter a time.");
  const value = new Date(raw);
  if (Number.isNaN(value.getTime())) throw new Error("Invalid time.");
  return value.toISOString();
}

function show(message) {
  const box = $("message");
  box.textContent = message;
  box.classList.add("show");
  clearTimeout(show._timer);
  show._timer = setTimeout(() => box.classList.remove("show"), 4500);
}

function ensureNativePort() {
  if (nativePort) return nativePort;
  const port = messenger.runtime.connectNative(HOST);

  port.onMessage.addListener(result => {
    if (result?.kind === "progress") {
      const waiter = nativeWaiters[0];
      if (!waiter || waiter.expired) return;
      if (typeof waiter.onProgress === "function") waiter.onProgress(result);
      return;
    }
    const waiter = nativeWaiters.shift();
    if (!waiter) return;
    if (waiter.timer) clearTimeout(waiter.timer);
    if (waiter.expired) return;
    if (!result || result.ok === false) {
      waiter.reject(new Error(result?.error || "Native Host returned an invalid response."));
      return;
    }
    waiter.resolve(result);
  });

  port.onDisconnect.addListener(() => {
    const detail = messenger.runtime.lastError?.message || "Native Host disconnected.";
    nativePort = null;
    while (nativeWaiters.length) {
      const waiter = nativeWaiters.shift();
      if (waiter.timer) clearTimeout(waiter.timer);
      if (!waiter.expired) waiter.reject(new Error(detail));
    }
  });

  nativePort = port;
  return port;
}

function host(message, timeoutMs = 30000, onProgress = null) {
  return new Promise((resolve, reject) => {
    const port = ensureNativePort();
    const waiter = {resolve, reject, expired: false, timer: null, onProgress};
    waiter.timer = setTimeout(() => {
      waiter.expired = true;
      reject(new Error(
        `Native Host did not answer “${message.command || "request"}” within ${timeoutMs} ms.`
      ));
    }, timeoutMs);
    nativeWaiters.push(waiter);
    try {
      port.postMessage(message);
    } catch (error) {
      const index = nativeWaiters.indexOf(waiter);
      if (index >= 0) nativeWaiters.splice(index, 1);
      clearTimeout(waiter.timer);
      reject(error);
    }
  });
}

function ensureDiagnosticPort() {
  if (diagnosticPort) return diagnosticPort;
  const port = messenger.runtime.connectNative(HOST);

  port.onMessage.addListener(result => {
    const waiter = diagnosticWaiters.shift();
    if (!waiter) return;
    if (waiter.timer) clearTimeout(waiter.timer);
    if (waiter.expired) return;
    if (!result || result.ok === false) {
      waiter.reject(new Error(result?.error || "Diagnostic Native Host returned an invalid response."));
      return;
    }
    waiter.resolve(result);
  });

  port.onDisconnect.addListener(() => {
    const detail = messenger.runtime.lastError?.message || "Diagnostic Native Host disconnected.";
    diagnosticPort = null;
    while (diagnosticWaiters.length) {
      const waiter = diagnosticWaiters.shift();
      if (waiter.timer) clearTimeout(waiter.timer);
      if (!waiter.expired) waiter.reject(new Error(detail));
    }
  });

  diagnosticPort = port;
  return port;
}

function diagnosticHost(message, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const port = ensureDiagnosticPort();
    const waiter = {resolve, reject, expired: false, timer: null};
    waiter.timer = setTimeout(() => {
      waiter.expired = true;
      reject(new Error(
        `Diagnostic log bridge did not answer “${message.command || "request"}” within ${timeoutMs} ms.`
      ));
    }, timeoutMs);
    diagnosticWaiters.push(waiter);
    try {
      port.postMessage(message);
    } catch (error) {
      const index = diagnosticWaiters.indexOf(waiter);
      if (index >= 0) diagnosticWaiters.splice(index, 1);
      clearTimeout(waiter.timer);
      reject(error);
    }
  });
}

function ensureIntegrationPort() {
  if (integrationPort) return integrationPort;
  const port = messenger.runtime.connectNative(HOST);

  port.onMessage.addListener(result => {
    if (result?.kind === "progress") {
      const waiter = integrationWaiters[0];
      if (!waiter || waiter.expired) return;
      if (typeof waiter.onProgress === "function") waiter.onProgress(result);
      return;
    }
    const waiter = integrationWaiters.shift();
    if (!waiter) return;
    if (waiter.timer) clearTimeout(waiter.timer);
    if (waiter.expired) return;
    if (!result || result.ok === false) {
      waiter.reject(new Error(result?.error || "Integration Native Host returned an invalid response."));
      return;
    }
    waiter.resolve(result);
  });

  port.onDisconnect.addListener(() => {
    const detail = messenger.runtime.lastError?.message || "Integration Native Host disconnected.";
    integrationPort = null;
    while (integrationWaiters.length) {
      const waiter = integrationWaiters.shift();
      if (waiter.timer) clearTimeout(waiter.timer);
      if (!waiter.expired) waiter.reject(new Error(detail));
    }
  });

  integrationPort = port;
  return port;
}

function integrationHost(message, timeoutMs = 60000, onProgress = null) {
  return new Promise((resolve, reject) => {
    const port = ensureIntegrationPort();
    const waiter = {resolve, reject, expired: false, timer: null, onProgress};
    waiter.timer = setTimeout(() => {
      waiter.expired = true;
      reject(new Error(
        `WordPress integration did not answer “${message.command || "request"}” within ${timeoutMs} ms.`
      ));
    }, timeoutMs);
    integrationWaiters.push(waiter);
    try {
      port.postMessage(message);
    } catch (error) {
      const index = integrationWaiters.indexOf(waiter);
      if (index >= 0) integrationWaiters.splice(index, 1);
      clearTimeout(waiter.timer);
      reject(error);
    }
  });
}

function selectedTaskId() {
  const value = selectedTaskIdValue || $("task").value;
  if (!value) throw new Error("Choose a task first.");
  return value;
}

function selectedTask() {
  const id = selectedTaskIdValue || $("task").value;
  return currentSnapshot.tasks.find(task => task.id === id) || null;
}

function stateForTask(task) {
  if (!task) return "none";
  if (currentSnapshot.state.current_task_id === task.id) return "current";
  if ((currentSnapshot.state.paused_task_ids || []).includes(task.id)) return "paused";
  return "ready";
}

function taskMeta(task) {
  const state = stateForTask(task);
  if (state === "current") return "▶ 正在工作";
  if (state === "paused") return "⏸ 已暂停";
  if (task.due) return `${task.status || "NEEDS-ACTION"} · due ${task.due}`;
  return task.status || "NEEDS-ACTION";
}

function selectTask(taskId) {
  if (!taskId || !currentSnapshot.tasks.some(task => task.id === taskId)) return;
  selectedTaskIdValue = taskId;
  $("task").value = taskId;
  renderTaskList();
  renderSelection();
}

function renderTaskList() {
  const container = $("task-list");
  const empty = $("task-empty");
  const query = $("task-search").value.trim().toLocaleLowerCase();
  container.textContent = "";

  const visible = currentSnapshot.tasks.filter(task =>
    !query || String(task.summary || "").toLocaleLowerCase().includes(query)
  );

  for (const task of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "task-item" + (task.id === selectedTaskIdValue ? " selected" : "");
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", task.id === selectedTaskIdValue ? "true" : "false");

    const title = document.createElement("span");
    title.className = "task-title";
    title.textContent = task.summary || "(untitled)";

    const meta = document.createElement("span");
    meta.className = "task-meta";
    meta.textContent = taskMeta(task);

    button.append(title, meta);
    button.addEventListener("click", () => selectTask(task.id));
    container.appendChild(button);
  }

  $("task-count").textContent = String(currentSnapshot.tasks.length);
  empty.hidden = visible.length !== 0;
}

function renderActionState() {
  const task = selectedTask();
  const state = stateForTask(task);
  const start = $("action-start");
  const pause = $("action-pause");
  const cancel = $("action-cancel");
  const complete = $("action-complete");
  const buttons = [start, pause, cancel, complete];

  for (const button of buttons) {
    button.hidden = true;
    button.disabled = actionBusy || !task;
  }
  if (!task) return;

  if (state === "current") {
    pause.hidden = false;
    cancel.hidden = false;
    complete.hidden = false;
    return;
  }

  if (state === "paused") {
    start.textContent = "继续";
    start.hidden = false;
    cancel.hidden = false;
    complete.hidden = false;
    return;
  }

  start.textContent = "开始";
  start.hidden = false;
}

function renderSelection() {
  const task = selectedTask();
  $("selected-task-title").textContent = task?.summary || "请选择任务";
  $("record-task-label").textContent = task
    ? `记录到：${task.summary}`
    : "先在“工作”中选择任务。";

  const currentId = currentSnapshot.state.current_task_id;
  const currentTask = currentSnapshot.tasks.find(item => item.id === currentId);
  $("task-status").textContent = currentId
    ? `Working: ${currentTask?.summary || currentId}`
    : "No active work";

  renderActionState();
}

function renderSnapshot(data) {
  const old = selectedTaskIdValue;
  currentSnapshot = data;

  const hiddenSelect = $("task");
  hiddenSelect.textContent = "";
  for (const task of data.tasks) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = task.summary;
    hiddenSelect.appendChild(option);
  }

  if (old && data.tasks.some(task => task.id === old)) {
    selectedTaskIdValue = old;
  } else if (data.state.current_task_id && data.tasks.some(task => task.id === data.state.current_task_id)) {
    selectedTaskIdValue = data.state.current_task_id;
  } else {
    selectedTaskIdValue = data.tasks[0]?.id || "";
  }
  hiddenSelect.value = selectedTaskIdValue;

  renderTaskList();
  renderSelection();

  const warning = $("work-warning");
  if (data.state.ambiguous) {
    warning.hidden = false;
    warning.textContent = "检测到多个打开的 Work VEVENT；在继续工作前需要先整理这些记录。";
  } else {
    warning.hidden = true;
    warning.textContent = "";
  }
}

async function localTasks() {
  if (!messenger.assistantCalendar?.listTasks) {
    throw new Error("Thunderbird local Calendar/Tasks bridge is unavailable.");
  }
  const started = performance.now();
  const tasks = await messenger.assistantCalendar.listTasks();
  const actionable = (tasks || []).filter(task => {
    const status = String(task.status || "").toUpperCase();
    return !task.completed && status !== "COMPLETED" && status !== "CANCELLED";
  });
  return {tasks: actionable, elapsedMs: performance.now() - started};
}

async function localWorkState() {
  if (!messenger.assistantCalendar?.workState) {
    throw new Error("Thunderbird local work-session bridge is unavailable.");
  }
  const started = performance.now();
  const work = await messenger.assistantCalendar.workState();
  return {work, elapsedMs: performance.now() - started};
}

function deriveState(tasks, work) {
  const currentId = work.currentTaskId || null;
  const worked = new Set(work.workedTaskIds || []);
  const paused = tasks
    .filter(task => {
      const status = String(task.status || "").toUpperCase();
      return status === "IN-PROCESS" && task.id !== currentId && worked.has(task.id);
    })
    .map(task => task.id);

  return {
    current_task_id: currentId,
    paused_task_ids: paused,
    ambiguous: Boolean(work.ambiguous),
    open_task_ids: work.openTaskIds || [],
    source: work.source || "thunderbird-calendar-cache",
  };
}

async function refreshFast() {
  const started = performance.now();
  const [tasksResult, workResult] = await Promise.allSettled([
    localTasks(),
    localWorkState(),
  ]);

  if (tasksResult.status === "fulfilled" && workResult.status === "fulfilled") {
    const elapsed = performance.now() - started;
    const localMs = Math.max(tasksResult.value.elapsedMs, workResult.value.elapsedMs);
    $("bridge-status").textContent = `Thunderbird 本地 · ${elapsed.toFixed(0)} ms`;
    $("bridge-status").className = "status-chip ok";
    $("metric-local").textContent = `${localMs.toFixed(0)} ms`;

    renderSnapshot({
      tasks: tasksResult.value.tasks,
      state: deriveState(tasksResult.value.tasks, workResult.value.work),
      today: currentSnapshot.today || [],
    });
    refreshToday().catch(error => {
      $("today").textContent = "Today unavailable: " + error.message;
    });
    return;
  }

  const reason = tasksResult.status === "rejected"
    ? tasksResult.reason
    : workResult.reason;
  $("bridge-status").textContent = "本地桥接失败 · CalDAV fallback";
  $("bridge-status").className = "status-chip warn";
  $("work-warning").hidden = false;
  $("work-warning").textContent =
    "Thunderbird 本地 Calendar/Tasks 读取不可用，正在使用较慢的兼容路径：" +
    (reason?.message || reason);

  const fallback = await host({command: "snapshot"}, 30000);
  renderSnapshot({
    tasks: fallback.tasks || [],
    state: fallback.state || {current_task_id: null, paused_task_ids: []},
    today: fallback.today || [],
  });
  renderToday(fallback.today || [], fallback.history_calendar?.name);
}

async function refreshToday() {
  const response = await host({command: "activity_today"}, 5000);
  currentSnapshot.today = response.today || [];
  renderToday(currentSnapshot.today, response.history_calendar?.name);
}

function renderToday(lines, historyName = "CalDAV Assistant History") {
  $("today").textContent = [
    `History: ${historyName || "CalDAV Assistant History"}`,
    ...(lines || []),
  ].join("\n");
}

function scheduleTaskRefresh() {
  if (taskRefreshTimer) clearTimeout(taskRefreshTimer);
  taskRefreshTimer = setTimeout(() => {
    taskRefreshTimer = null;
    refreshFast().catch(error => show(error.message));
  }, 100);
}

function actionProgressLabel(action) {
  return {
    start: "正在开始…",
    resume: "正在继续…",
    pause: "正在暂停…",
    cancel: "正在取消…",
    complete: "正在完成…",
  }[action] || "正在处理…";
}

let visibleOperationId = "";

function newOperationId(prefix = "tb") {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setOperationMonitor({
  doing = "—",
  peer = "—",
  sent = "—",
  waiting = "—",
  received = "—",
  next = "—",
} = {}) {
  $("operation-doing").textContent = doing;
  $("operation-peer").textContent = peer;
  $("operation-sent").textContent = sent;
  $("operation-waiting").textContent = waiting;
  $("operation-received").textContent = received;
  $("operation-next").textContent = next;
}

function resetOperationTrace() {
  $("operation-trace").textContent = "";
}

function appendOperationTrace(message, state = "info") {
  const row = document.createElement("li");
  row.className = `trace-${state}`;
  row.textContent = message;
  $("operation-trace").appendChild(row);
  while ($("operation-trace").children.length > 16) {
    $("operation-trace").firstElementChild.remove();
  }
}

function compactId(value) {
  const text = String(value || "");
  return text.length > 18 ? text.slice(0, 8) + "…" + text.slice(-6) : text;
}

function renderCoreProgress(progress, operationId) {
  if (visibleOperationId !== operationId) return;
  const details = progress.details || {};
  const state = progress.state || "info";
  const taskId = compactId(details.task_id);
  const stage = progress.stage || "";

  if (stage === "history.ensure" && state === "started") {
    setOperationMonitor({
      doing: "准备工作历史日历",
      peer: "CalDAV Assistant Core ↔ Radicale",
      sent: "检查并创建 CalDAV Assistant History collection",
      waiting: "等待 Radicale 确认 History collection 可用",
      received: "—",
      next: "随后读取 Task 与 Work 权威状态",
    });
  } else if (stage === "history.ensure" && state === "done") {
    setOperationMonitor({
      doing: "工作历史日历已就绪",
      peer: "Radicale · CalDAV",
      sent: "History collection provisioning",
      waiting: "无",
      received: details.created ? "已新建 CalDAV Assistant History" : "已复用现有 History collection",
      next: "继续当前 Task 操作",
    });
  } else if (stage === "action.preflight") {
    setOperationMonitor({
      doing: "验证任务与当前工作时段",
      peer: "CalDAV Assistant Core ↔ Radicale",
      sent: `读取 Task ${taskId || "当前任务"} 与 Work VEVENT 状态`,
      waiting: "等待 Radicale 返回权威 CalDAV 状态",
      received: "—",
      next: "校验通过后执行任务动作",
    });
  } else if (stage === "caldav.preflight" && state === "started") {
    setOperationMonitor({
      doing: "并行读取权威状态",
      peer: "Radicale · Task collection + Work collection",
      sent: `同时读取 VTODO ${taskId} 与 open Work VEVENT`,
      waiting: "等待两条 CalDAV 读取都返回；较慢的一条决定这一阶段耗时",
      received: "—",
      next: "用同一轮权威状态做生命周期校验",
    });
  } else if (stage === "caldav.preflight" && state === "done") {
    setOperationMonitor({
      doing: "权威状态读取完成",
      peer: "Radicale · CalDAV",
      sent: `VTODO + open Work query · Task ${taskId}`,
      waiting: "无",
      received: `STATUS=${details.status || "?"} · open work=${details.open_work_count ?? "?"}`,
      next: "执行当前 Task 动作",
    });
  } else if (stage === "wordpress.queue" && state === "started") {
    setOperationMonitor({
      doing: "保存 WordPress 日志到本地 Outbox",
      peer: "CalDAV Assistant · SQLite WordPress Outbox",
      sent: `Task ${taskId} 的日志记录`,
      waiting: "等待本地持久化确认，不等待 WordPress 网络",
      received: "—",
      next: "Outbox 成功后独立上传 WordPress",
    });
  } else if (stage === "wordpress.queue" && state === "done") {
    setOperationMonitor({
      doing: "WordPress 日志已安全入队",
      peer: "SQLite WordPress Outbox",
      sent: `Task ${taskId} log`,
      waiting: "无",
      received: `Outbox pending=${details.pending ?? "?"}`,
      next: "独立通道上传 WordPress",
    });
  } else if (stage === "worklog.open" && state === "started") {
    setOperationMonitor({
      doing: "创建工作时段",
      peer: "Radicale · CalDAV Work collection",
      sent: `创建 VEVENT · Task-UID=${taskId}`,
      waiting: "等待服务器确认 VEVENT 已创建",
      received: "—",
      next: "随后写入 Task 的 IN-PROCESS 状态",
    });
  } else if (stage === "worklog.open" && state === "done") {
    setOperationMonitor({
      doing: "工作时段已创建",
      peer: "Radicale · CalDAV Work collection",
      sent: "VEVENT create",
      waiting: "无",
      received: `VEVENT ${compactId(details.event_id)} · DTSTART ${details.start || "已确认"}`,
      next: "继续写入 Task 状态",
    });
  } else if (stage === "worklog.close" && state === "started") {
    setOperationMonitor({
      doing: "关闭当前工作时段",
      peer: "Radicale · CalDAV Work collection",
      sent: `更新 VEVENT ${compactId(details.event_id)}：写入 DTEND，移除 open 标记`,
      waiting: "等待服务器确认 Work VEVENT 更新",
      received: "—",
      next: "随后写入 Task 状态 / 保存日志 Outbox",
    });
  } else if (stage === "worklog.close" && state === "done") {
    setOperationMonitor({
      doing: "工作时段已关闭",
      peer: "Radicale · CalDAV Work collection",
      sent: `VEVENT ${compactId(details.event_id)} update`,
      waiting: "无",
      received: `DTEND ${details.end || "已确认"}`,
      next: "继续处理 Task 状态",
    });
  } else if (stage === "task.write" && state === "started") {
    const fields = Array.isArray(details.fields) ? details.fields.join(", ") : "Task fields";
    setOperationMonitor({
      doing: "写入任务状态",
      peer: "Radicale · CalDAV Task collection",
      sent: `VTODO ${taskId} · ${fields}`,
      waiting: "等待 Radicale 返回 VTODO 更新确认",
      received: "—",
      next: "确认后才向界面报告成功",
    });
  } else if (stage === "task.write" && state === "done") {
    setOperationMonitor({
      doing: "任务状态已确认",
      peer: "Radicale · CalDAV Task collection",
      sent: `VTODO ${taskId} update`,
      waiting: "无",
      received: `STATUS=${details.status || "已更新"} · completed=${Boolean(details.completed)}`,
      next: "更新界面；WordPress 不阻塞此成功结果",
    });
  } else if (stage === "action.commit") {
    setOperationMonitor({
      doing: "CalDAV 动作完成",
      peer: "CalDAV Assistant Core",
      sent: `${details.action || "action"} · Task ${taskId}`,
      waiting: "无",
      received: "Core 已确认成功",
      next: "如有工作日志，转交 WordPress Outbox 独立同步",
    });
  } else if (stage === "wordpress.background") {
    setOperationMonitor({
      doing: "WordPress 日志已交给后台服务",
      peer: "SQLite WordPress Outbox → Assistant Background Service",
      sent: `持久队列状态 · pending=${details.pending ?? "?"}`,
      waiting: "前台不等待 WordPress 上传；后台 Assistant Service 负责发送与重试",
      received: "Outbox 已安全保存",
      next: "当前独立通道只继续建立 Calendar ↔ WordPress 回链",
    });
  } else if (stage === "wordpress.calendar_link" && state === "started") {
    setOperationMonitor({
      doing: "建立 Calendar ↔ WordPress 回链",
      peer: "WordPress + Radicale Work VEVENT",
      sent: `查找 Task ${taskId} 的工作事件并写入 WordPress URL`,
      waiting: "等待 WordPress 日志 URL 与 CalDAV VEVENT 更新确认",
      received: "—",
      next: "完成后整个集成链闭环",
    });
  } else if (stage === "wordpress.calendar_link" && state === "done") {
    setOperationMonitor({
      doing: "Calendar ↔ WordPress 已连接",
      peer: "Radicale · CalDAV Work collection",
      sent: `更新 VEVENT ${compactId(details.event_id)} 引用`,
      waiting: "无",
      received: details.wordpress_url ? `WordPress URL: ${details.wordpress_url}` : "链接步骤完成",
      next: "完成",
    });
  } else if (stage === "wordpress.calendar_link" && state === "failed") {
    setOperationMonitor({
      doing: "Calendar ↔ WordPress 回链未完成",
      peer: "WordPress / Radicale",
      sent: `Task ${taskId} link request`,
      waiting: "等待后续重试",
      received: details.error || "当前未能建立链接",
      next: "WordPress 日志仍保留在 Outbox，不影响 Task 已完成状态",
    });
  } else {
    setOperationMonitor({
      doing: progress.message || stage || "正在处理",
      peer: "CalDAV Assistant Core",
      sent: taskId ? `Task ${taskId}` : "内部请求",
      waiting: state === "started" ? "等待当前步骤完成" : "无",
      received: state === "done" ? "已完成" : state === "failed" ? "失败" : "—",
      next: "继续下一步",
    });
  }
  appendOperationTrace(progress.message || stage, state);
}

async function runWordpressFollowUp(followUp, parentOperationId) {
  if (!followUp) return;
  const operationId = newOperationId("wordpress");
  if (visibleOperationId === parentOperationId) visibleOperationId = operationId;
  if (visibleOperationId === operationId) {
    appendOperationTrace("Task 操作已完成；WordPress 改由独立通道继续。", "info");
    setOperationMonitor({
      doing: "交接 WordPress 后续工作",
      peer: "SQLite Outbox + Assistant Background Service + 独立回链通道",
      sent: `检查 Outbox · Task ${compactId(followUp.task_id)}；如启用则建立 Calendar 回链`,
      waiting: "不等待 WordPress 日志上传；只等待可选的 WordPress URL / CalDAV 回链确认",
      received: "CalDAV Task 动作已成功，日志已持久入队",
      next: "后台服务负责上传和重试；本通道完成 Calendar ↔ WordPress 链接",
    });
  }

  try {
    const response = await integrationHost(
      {...followUp, operation_id: operationId},
      60000,
      progress => renderCoreProgress(progress, operationId)
    );
    if (visibleOperationId === operationId) {
      const wp = response.wordpress || {};
      const pendingKnown = typeof wp.pending === "number";
      const waiting = !pendingKnown
        ? "Outbox 数量未知；Background Service 仍负责 WordPress 发送与重试"
        : wp.pending > 0
          ? "WordPress 日志仍在后台 Outbox，等待 Background Service 下一次发送/重试"
          : "无";
      setOperationMonitor({
        doing: "WordPress 集成交接完成",
        peer: "Assistant Background Service + WordPress + Radicale",
        sent: "Outbox ownership check + Calendar reference",
        waiting,
        received: `delivery=${wp.delivery_owner || "background-service"} · pending=${wp.pending ?? "unknown"} · calendar-link=${wp.calendar_link_state || "unknown"}`,
        next: pendingKnown && wp.pending === 0
          ? "WordPress 队列已清空；前台可以继续工作"
          : "后台服务继续发送/重试；前台可以继续工作",
      });
      appendOperationTrace("WordPress follow-up finished.", "done");
    }
    refreshLogs().catch(() => {});
  } catch (error) {
    if (visibleOperationId === operationId) {
      setOperationMonitor({
        doing: "WordPress 回链后续未完成",
        peer: "WordPress Integration Native Host",
        sent: "Outbox 状态 / Calendar reference",
        waiting: "WordPress 日志仍由 Background Service 从 Outbox 重试；回链需要后续重试",
        received: error.message,
        next: "Task 的 CalDAV 成功结果保持不变；Outbox 数据不会丢失",
      });
      appendOperationTrace("WordPress follow-up pending: " + error.message, "failed");
    }
  }
}

function applySuccessfulAction(action, taskId) {
  const state = currentSnapshot.state;
  const paused = new Set(state.paused_task_ids || []);

  if (action === "start" || action === "resume") {
    state.current_task_id = taskId;
    paused.delete(taskId);
  } else if (action === "pause") {
    state.current_task_id = null;
    paused.add(taskId);
  } else if (action === "complete" || action === "cancel") {
    if (state.current_task_id === taskId) state.current_task_id = null;
    paused.delete(taskId);
    currentSnapshot.tasks = currentSnapshot.tasks.filter(task => task.id !== taskId);
    if (selectedTaskIdValue === taskId) {
      selectedTaskIdValue = currentSnapshot.tasks[0]?.id || "";
    }
  }

  state.paused_task_ids = [...paused];
  renderSnapshot(currentSnapshot);
}

async function doAction(action) {
  const task = selectedTask();
  if (!task) throw new Error("Choose a task first.");

  const requestedAction =
    action === "start" && stateForTask(task) === "paused" ? "resume" : action;
  const operationId = newOperationId("caldav");
  const at = isoFromInput();
  visibleOperationId = operationId;
  resetOperationTrace();
  setOperationMonitor({
    doing: actionProgressLabel(requestedAction).replace("…", ""),
    peer: "Thunderbird → 本地 CalDAV Assistant Native Host",
    sent: `action=${requestedAction} · Task=${task.summary} (${compactId(task.id)}) · at=${at}`,
    waiting: "等待 Core 校验，并等待 Radicale 对权威 CalDAV 写入的确认",
    received: "—",
    next: "CalDAV 成功后立即更新界面；WordPress 使用独立后续通道",
  });
  appendOperationTrace("已把动作交给本地 CalDAV Assistant Core。", "started");

  actionBusy = true;
  $("operation-status").textContent = actionProgressLabel(requestedAction);
  renderActionState();

  const started = performance.now();
  try {
    const response = await host(
      {
        command: "action",
        action: requestedAction,
        task_id: task.id,
        task,
        at,
        calendar_link: $("calendar-link").checked,
        operation_id: operationId,
      },
      30000,
      progress => renderCoreProgress(progress, operationId)
    );
    const elapsed = performance.now() - started;
    $("metric-core").textContent = `${elapsed.toFixed(0)} ms`;
    $("operation-status").textContent = `CalDAV 已确认 · ${elapsed.toFixed(0)} ms`;
    applySuccessfulAction(requestedAction, task.id);

    const wp = response.wordpress;
    if (visibleOperationId === operationId) {
      setOperationMonitor({
        doing: "CalDAV Task 动作已完成",
        peer: "CalDAV Assistant Core ↔ Radicale",
        sent: `action=${requestedAction} · Task=${compactId(task.id)}`,
        waiting: wp ? "不再等待 WordPress；WordPress 将在独立通道继续" : "无",
        received: `${response.message} · Core ${elapsed.toFixed(0)} ms`,
        next: wp ? "WordPress Outbox 上传 + Calendar 回链" : "完成",
      });
      appendOperationTrace(`CalDAV 权威操作已确认（${elapsed.toFixed(0)} ms）。`, "done");
    }

    show(response.message + (wp?.message ? " · " + wp.message : ""));
    $("when").value = localInputNow();

    setTimeout(() => refreshFast().catch(() => {}), 250);
    refreshLogs().catch(() => {});
    runWordpressFollowUp(response.follow_up, operationId);
  } catch (error) {
    $("operation-status").textContent = "操作失败";
    if (visibleOperationId === operationId) {
      setOperationMonitor({
        doing: "操作失败",
        peer: "CalDAV Assistant Core / Radicale",
        sent: `action=${requestedAction} · Task=${compactId(task.id)}`,
        waiting: "无",
        received: error.message,
        next: "未把失败伪装成成功；请根据错误修正后重试",
      });
      appendOperationTrace("失败：" + error.message, "failed");
    }
    show(error.message);
    throw error;
  } finally {
    actionBusy = false;
    renderActionState();
  }
}

async function addNote() {
  const task = selectedTask();
  if (!task) throw new Error("Choose a task first.");
  const text = $("note").value.trim();
  if (!text) throw new Error("Write a note first.");

  const operationId = newOperationId("note");
  const at = isoFromInput();
  visibleOperationId = operationId;
  resetOperationTrace();
  setOperationMonitor({
    doing: "保存工作记录",
    peer: "Thunderbird → 本地 CalDAV Assistant Native Host",
    sent: `WordPress note · Task=${task.summary} (${compactId(task.id)}) · ${text.length} chars`,
    waiting: "等待写入本地持久 Outbox；不等待 WordPress 网络上传",
    received: "—",
    next: "入队后立即返回；WordPress 独立同步",
  });
  appendOperationTrace("正在把工作记录写入 WordPress Outbox。", "started");

  $("add-note").disabled = true;
  try {
    const response = await host(
      {
        command: "note",
        task_id: task.id,
        text,
        at,
        calendar_link: $("calendar-link").checked,
        operation_id: operationId,
      },
      10000,
      progress => renderCoreProgress(progress, operationId)
    );
    $("note").value = "";
    if (visibleOperationId === operationId) {
      setOperationMonitor({
        doing: "工作记录已保存",
        peer: "SQLite WordPress Outbox",
        sent: `${text.length} chars · Task ${compactId(task.id)}`,
        waiting: "不等待 WordPress",
        received: response.message || "Saved to WordPress Outbox.",
        next: "独立通道上传 WordPress 并补 Calendar 回链",
      });
      appendOperationTrace("工作记录已安全进入本地 Outbox。", "done");
    }
    show(response.message || "Saved to WordPress Outbox.");
    runWordpressFollowUp(response.follow_up, operationId);
    refreshLogs().catch(() => {});
  } catch (error) {
    if (visibleOperationId === operationId) {
      setOperationMonitor({
        doing: "工作记录保存失败",
        peer: "CalDAV Assistant local Outbox",
        sent: `${text.length} chars`,
        waiting: "无",
        received: error.message,
        next: "记录未被伪装成已保存",
      });
      appendOperationTrace("失败：" + error.message, "failed");
    }
    throw error;
  } finally {
    $("add-note").disabled = false;
  }
}

async function copyText(text, label) {
  const value = String(text || "");
  if (!value) throw new Error("Nothing to copy.");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
  } else {
    const area = document.createElement("textarea");
    area.value = value;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) throw new Error("Copy failed.");
  }
  show(label + " copied.");
}

function renderLogError(error) {
  const detail = error?.message || String(error || "Unknown Native Host error");
  $("log-status").textContent = "日志不可达";
  $("log-path").textContent = EXPECTED_LOG_PATH;
  $("copy-log-path").hidden = false;
  $("logs").textContent =
    "The log bridge did not answer.\n\n" +
    detail +
    "\n\nExpected log file:\n" +
    EXPECTED_LOG_PATH;
  $("log-rows").innerHTML = "";
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = 4;
  cell.textContent = detail;
  row.appendChild(cell);
  $("log-rows").appendChild(row);
}

function parseLogLines(lines) {
  return (lines || []).map(line => {
    try {
      return {raw: line, data: JSON.parse(line)};
    } catch (_error) {
      return {raw: line, data: null};
    }
  });
}

function biggestTiming(timings) {
  if (!timings || typeof timings !== "object") return null;
  const skip = new Set(["total_ms", "host_total_ms"]);
  const values = Object.entries(timings)
    .filter(([key, value]) => !skip.has(key) && typeof value === "number")
    .sort((a, b) => b[1] - a[1]);
  return values[0] || null;
}

function renderStructuredLogs(lines) {
  const parsed = parseLogLines(lines);
  const requests = parsed
    .map(item => item.data)
    .filter(item => item && item.event === "request");

  const rows = $("log-rows");
  rows.textContent = "";

  const recent = requests.slice(-100).reverse();
  if (!recent.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.textContent = "还没有请求日志。";
    row.appendChild(cell);
    rows.appendChild(row);
  }

  for (const item of recent) {
    const row = document.createElement("tr");
    const at = String(item.at || "").split("T")[1]?.slice(0, 12) || "—";
    const total = typeof item.total_ms === "number" ? `${item.total_ms.toFixed(1)} ms` : "—";
    const biggest = biggestTiming(item.timings);
    const phase = biggest ? `${biggest[0]} · ${biggest[1].toFixed(1)} ms` : "—";
    for (const value of [at, item.command || item.event || "—", total, phase]) {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.appendChild(cell);
    }
    rows.appendChild(row);
  }

  const latest = requests[requests.length - 1];
  if (latest && typeof latest.total_ms === "number") {
    $("metric-core").textContent = `${latest.total_ms.toFixed(0)} ms`;
    const biggest = biggestTiming(latest.timings);
    $("latency-summary").textContent = biggest
      ? `${latest.command} · ${latest.total_ms.toFixed(0)} ms · ${biggest[0]} ${biggest[1].toFixed(0)} ms`
      : `${latest.command} · ${latest.total_ms.toFixed(0)} ms`;
  } else {
    $("latency-summary").textContent = "暂无可分析请求";
  }
}

async function refreshLogs() {
  $("log-status").textContent = "正在读取…";
  try {
    const response = await diagnosticHost({command: "logs", limit: 300}, 5000);
    const path = response.path || EXPECTED_LOG_PATH;
    const lines = response.lines || [];
    $("log-status").textContent = "已连接 · 日志可读";
    $("log-path").textContent = path;
    $("copy-log-path").hidden = false;
    $("logs").textContent = lines.join("\n") || "No log entries yet.";
    renderStructuredLogs(lines);
    return response;
  } catch (error) {
    renderLogError(error);
    throw error;
  }
}

async function clearLogs() {
  await diagnosticHost({command: "logs_clear"}, 5000);
  $("logs").textContent = "No log entries yet.";
  $("log-status").textContent = "已连接 · 日志可读";
  renderStructuredLogs([]);
  show("Logs cleared.");
}

async function openLogFolder() {
  const response = await diagnosticHost({command: "logs_open"}, 5000);
  if (response.path) {
    $("log-path").textContent = response.path;
    $("copy-log-path").hidden = false;
  }
  show(response.opened ? "Log folder opened." : "Copy the path to open it manually.");
}

function startLogAutoRefresh() {
  if (logAutoRefreshTimer) return;
  logAutoRefreshTimer = setInterval(() => {
    if (!document.hidden && activeTab === "diagnostics") {
      refreshLogs().catch(() => {});
    }
  }, 3000);
}

function bytesToBase64(bytes) {
  let binary = "";
  const stride = 0x8000;
  for (let i = 0; i < bytes.length; i += stride) {
    binary += String.fromCharCode(...bytes.subarray(i, i + stride));
  }
  return btoa(binary);
}

async function uploadOneFile(file, row) {
  const task = selectedTask();
  if (!task) throw new Error("Choose a task first.");

  const common = {
    task_id: task.id,
    filename: file.name,
    mime_type: file.type || "application/octet-stream",
    at: isoFromInput(),
    calendar_link: $("calendar-link").checked,
    attachment_link: $("attachment-link").checked,
  };

  const begin = await host({
    command: "attachment_begin",
    ...common,
    total_size: file.size,
  });
  const uploadId = begin.upload_id;

  try {
    let sent = 0;
    while (sent < file.size) {
      const blob = file.slice(sent, sent + ATTACHMENT_CHUNK_BYTES);
      const bytes = new Uint8Array(await blob.arrayBuffer());
      await host({
        command: "attachment_chunk",
        upload_id: uploadId,
        data_base64: bytesToBase64(bytes),
      });
      sent += bytes.length;
      const pct = file.size ? Math.min(100, Math.round((sent / file.size) * 100)) : 100;
      row.textContent = `Uploading ${file.name}… ${pct}%`;
    }
    return await host({command: "attachment_finish", upload_id: uploadId});
  } catch (error) {
    host({command: "attachment_abort", upload_id: uploadId}).catch(() => {});
    throw error;
  }
}

async function uploadFiles(files) {
  const area = $("uploads");
  for (const file of files) {
    const row = document.createElement("div");
    row.textContent = "Uploading " + file.name + "…";
    area.appendChild(row);
    try {
      const response = await uploadOneFile(file, row);
      row.textContent = "✓ " + file.name + (response.url ? " → " + response.url : " (queued)");
    } catch (error) {
      row.textContent = "✗ " + file.name + ": " + error.message;
    }
  }
  refreshLogs().catch(() => {});
}

async function loadSettings() {
  const stored = await messenger.storage.local.get({
    calendarLink: true,
    attachmentLink: false,
  });
  $("calendar-link").checked = stored.calendarLink;
  $("attachment-link").checked = stored.attachmentLink;
}

function activateTab(name) {
  activeTab = name;
  for (const button of document.querySelectorAll(".tab")) {
    const active = button.dataset.tab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }
  for (const panel of document.querySelectorAll("[data-panel]")) {
    const active = panel.dataset.panel === name;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  }
  if (name === "diagnostics") refreshLogs().catch(() => {});
  if (name === "today") refreshToday().catch(error => show(error.message));
}

for (const button of document.querySelectorAll(".tab")) {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
}

$("task-search").addEventListener("input", renderTaskList);
$("use-now").addEventListener("click", () => {
  $("when").value = localInputNow();
  $("operation-status").textContent = "时间已更新为现在";
});
$("refresh").addEventListener("click", () => refreshFast().catch(error => show(error.message)));
$("refresh-logs").addEventListener("click", () => refreshLogs().catch(error => show(error.message)));
$("copy-today").addEventListener("click", () =>
  copyText($("today").textContent, "Today").catch(error => show(error.message))
);
$("copy-logs").addEventListener("click", () =>
  copyText($("logs").textContent, "Logs").catch(error => show(error.message))
);
$("copy-log-path").addEventListener("click", () =>
  copyText($("log-path").textContent, "Log path").catch(error => show(error.message))
);
$("open-log-folder").addEventListener("click", () =>
  openLogFolder().catch(error => {
    renderLogError(error);
    show(error.message);
  })
);
$("clear-logs").addEventListener("click", () => clearLogs().catch(error => show(error.message)));

for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () =>
    doAction(button.dataset.action).catch(() => {})
  );
}

$("add-note").addEventListener("click", () => addNote().catch(error => show(error.message)));
$("attachment").addEventListener("change", event => {
  uploadFiles([...event.target.files]).catch(error => show(error.message));
  event.target.value = "";
});
$("calendar-link").addEventListener("change", () =>
  messenger.storage.local.set({calendarLink: $("calendar-link").checked})
);
$("attachment-link").addEventListener("change", () =>
  messenger.storage.local.set({attachmentLink: $("attachment-link").checked})
);

if (messenger.assistantCalendar?.onTasksChanged) {
  messenger.assistantCalendar.onTasksChanged.addListener(scheduleTaskRefresh);
}

window.addEventListener("pagehide", () => {
  if (taskRefreshTimer) clearTimeout(taskRefreshTimer);
  if (logAutoRefreshTimer) clearInterval(logAutoRefreshTimer);
  if (nativePort) nativePort.disconnect();
  if (diagnosticPort) diagnosticPort.disconnect();
  if (integrationPort) integrationPort.disconnect();
  nativePort = null;
  diagnosticPort = null;
  integrationPort = null;
});

$("version-badge").textContent = "v" + messenger.runtime.getManifest().version;
$("when").value = localInputNow();

loadSettings()
  .then(async () => {
    await Promise.allSettled([
      refreshFast().catch(error => show(error.message)),
      refreshLogs().catch(() => {}),
    ]);
    startLogAutoRefresh();
  })
  .catch(error => show(error.message));
