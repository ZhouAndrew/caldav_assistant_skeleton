const HOST = "local.caldav_assistant_experimental";
const ATTACHMENT_CHUNK_BYTES = 256 * 1024;
const $ = (id) => document.getElementById(id);

let nativePort = null;
const nativeWaiters = [];
let diagnosticPort = null;
const diagnosticWaiters = [];
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

function host(message, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const port = ensureNativePort();
    const waiter = {resolve, reject, expired: false, timer: null};
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
    pause: "正在暂停…",
    cancel: "正在取消…",
    complete: "正在完成…",
  }[action] || "正在处理…";
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

  actionBusy = true;
  $("operation-status").textContent = actionProgressLabel(requestedAction);
  renderActionState();

  const started = performance.now();
  try {
    const response = await host({
      command: "action",
      action: requestedAction,
      task_id: task.id,
      task,
      at: isoFromInput(),
      calendar_link: $("calendar-link").checked,
    });
    const elapsed = performance.now() - started;
    $("metric-core").textContent = `${elapsed.toFixed(0)} ms`;
    $("operation-status").textContent = `已同步 · ${elapsed.toFixed(0)} ms`;
    applySuccessfulAction(requestedAction, task.id);

    const wp = response.wordpress;
    show(response.message + (wp?.message ? " · " + wp.message : ""));
    $("when").value = localInputNow();

    setTimeout(() => refreshFast().catch(() => {}), 250);
    refreshLogs().catch(() => {});
  } catch (error) {
    $("operation-status").textContent = "操作失败";
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

  $("add-note").disabled = true;
  try {
    const response = await host({
      command: "note",
      task_id: task.id,
      text,
      at: isoFromInput(),
      calendar_link: $("calendar-link").checked,
    });
    $("note").value = "";
    show(response.message || "Added to WordPress.");
    refreshLogs().catch(() => {});
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
  nativePort = null;
  diagnosticPort = null;
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
