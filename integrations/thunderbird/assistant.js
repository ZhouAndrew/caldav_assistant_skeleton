const HOST = "local.caldav_assistant_experimental";
const ATTACHMENT_CHUNK_BYTES = 256 * 1024;
const $ = (id) => document.getElementById(id);

let nativePort = null;
const nativeWaiters = [];
let diagnosticPort = null;
const diagnosticWaiters = [];
let currentSnapshot = null;
let taskRefreshTimer = null;
let logAutoRefreshTimer = null;
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
  setTimeout(() => box.classList.remove("show"), 4000);
}

function ensureNativePort() {
  if (nativePort) return nativePort;

  const port = messenger.runtime.connectNative(HOST);
  port.onMessage.addListener((result) => {
    const waiter = nativeWaiters.shift();
    if (!waiter) return;

    if (waiter.timer) clearTimeout(waiter.timer);
    // A timed-out request remains in the FIFO until its delayed response
    // arrives. Discard that one response instead of giving it to a newer call.
    if (waiter.expired) return;

    if (!result || result.ok === false) {
      waiter.reject(new Error(result?.error || "Native host returned an invalid response."));
      return;
    }
    waiter.resolve(result);
  });
  port.onDisconnect.addListener(() => {
    const detail = messenger.runtime.lastError?.message || "Native host disconnected.";
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
  const value = $("task").value;
  if (!value) throw new Error("Choose a task first.");
  return value;
}

function selectedTask() {
  const id = selectedTaskId();
  return currentSnapshot?.tasks?.find(task => task.id === id) || null;
}

function taskLabel(task, state) {
  const marks = [];
  if (state.current_task_id === task.id) marks.push("▶");
  if ((state.paused_task_ids || []).includes(task.id)) marks.push("⏸");
  return (marks.length ? marks.join("") + " " : "") + task.summary;
}

function renderActionState() {
  const data = currentSnapshot;
  const taskId = $("task").value;
  const task = data?.tasks?.find(item => item.id === taskId) || null;
  const current = Boolean(task && data?.state?.current_task_id === taskId);
  const paused = Boolean(task && (data?.state?.paused_task_ids || []).includes(taskId));

  const start = $("action-start");
  const pause = $("action-pause");
  const cancel = $("action-cancel");
  const complete = $("action-complete");
  const buttons = [start, pause, cancel, complete];

  for (const button of buttons) {
    button.hidden = true;
    button.disabled = !task;
  }
  if (!task) return;

  if (current) {
    pause.hidden = false;
    cancel.hidden = false;
    complete.hidden = false;
    return;
  }

  if (paused) {
    start.textContent = "继续";
    start.hidden = false;
    cancel.hidden = false;
    complete.hidden = false;
    return;
  }

  start.textContent = "开始";
  start.hidden = false;
}

function renderSnapshot(data, bridgeText) {
  currentSnapshot = data;
  const select = $("task");
  const old = select.value;
  select.textContent = "";

  for (const task of data.tasks || []) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = taskLabel(task, data.state || {});
    select.appendChild(option);
  }

  if (old && data.tasks.some(task => task.id === old)) {
    select.value = old;
  }
  if (!select.value && data.state?.current_task_id) {
    select.value = data.state.current_task_id;
  }
  select.disabled = data.tasks.length === 0;

  $("bridge-status").textContent = bridgeText;
  $("task-status").textContent = data.state?.current_task_id
    ? "Working: " + (
        data.tasks.find(task => task.id === data.state.current_task_id)?.summary ||
        data.state.current_task_id
      )
    : "No active work";

  renderActionState();

  const history = data.history_calendar?.name || "CalDAV Assistant History";
  const lines = data.today || [];
  $("today").textContent = [`History: ${history}`, ...lines].join("\n");
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
  return {
    tasks: actionable,
    elapsedMs: performance.now() - started,
  };
}

async function refresh() {
  const stateStarted = performance.now();
  const [tasksResult, stateResult] = await Promise.allSettled([
    localTasks(),
    host({command: "state"}),
  ]);

  if (tasksResult.status === "fulfilled" && stateResult.status === "fulfilled") {
    const stateElapsed = performance.now() - stateStarted;
    const nativeMs = Number(stateResult.value.timings?.total_ms || 0);
    const data = {
      ...stateResult.value,
      tasks: tasksResult.value.tasks,
    };
    renderSnapshot(
      data,
      `Thunderbird local ${tasksResult.value.elapsedMs.toFixed(0)} ms · Core ${nativeMs.toFixed(0)} ms · UI ${stateElapsed.toFixed(0)} ms`
    );
    return;
  }

  // Compatibility fallback for an older XPI/Thunderbird where the local
  // calendar experiment cannot load. This path may use the slower CalDAV read.
  const fallback = await host({command: "snapshot"});
  renderSnapshot(fallback, "Core connected · CalDAV fallback");
  if (tasksResult.status === "rejected") {
    show("Local task cache unavailable; using CalDAV fallback: " + tasksResult.reason.message);
  }
}

function scheduleTaskRefresh() {
  if (taskRefreshTimer) clearTimeout(taskRefreshTimer);
  taskRefreshTimer = setTimeout(() => {
    taskRefreshTimer = null;
    refresh().catch(error => show(error.message));
  }, 80);
}

async function doAction(action) {
  const task = selectedTask();
  const started = performance.now();
  const response = await host({
    command: "action",
    action,
    task_id: selectedTaskId(),
    task,
    at: isoFromInput(),
    calendar_link: $("calendar-link").checked,
  });
  const elapsed = performance.now() - started;
  const wp = response.wordpress;
  show(
    response.message +
    (wp?.message ? " · " + wp.message : "") +
    ` · ${elapsed.toFixed(0)} ms`
  );
  $("when").value = localInputNow();
  await refresh();
  refreshLogs().catch(() => {});
}

async function addNote() {
  const text = $("note").value.trim();
  if (!text) throw new Error("Write a note first.");
  const response = await host({
    command: "note",
    task_id: selectedTaskId(),
    text,
    at: isoFromInput(),
    calendar_link: $("calendar-link").checked,
  });
  $("note").value = "";
  show(response.message || "Added to WordPress.");
  refreshLogs().catch(() => {});
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
  const meta = $("log-status").parentElement;
  meta.dataset.state = "error";
  $("log-status").textContent = "Log unavailable — Retry after repairing Native Host";
  $("log-path").textContent = EXPECTED_LOG_PATH;
  $("copy-log-path").hidden = false;
  $("logs").textContent =
    "The log bridge did not answer.\n\n" +
    detail +
    "\n\nExpected log file:\n" +
    EXPECTED_LOG_PATH +
    "\n\nUse Retry after reinstalling/updating the Native Host.";
}

async function refreshLogs() {
  const meta = $("log-status").parentElement;
  meta.dataset.state = "loading";
  $("log-status").textContent = "Connecting to Native Host…";
  $("logs").textContent = "Connecting…";

  try {
    const response = await diagnosticHost({command: "logs", limit: 300}, 5000);
    const path = response.path || EXPECTED_LOG_PATH;
    meta.dataset.state = "ok";
    $("log-status").textContent = "Connected · log readable";
    $("log-path").textContent = path;
    $("copy-log-path").hidden = false;
    $("logs").textContent = (response.lines || []).join("\n") || "No log entries yet.";
    return response;
  } catch (error) {
    renderLogError(error);
    throw error;
  }
}

async function clearLogs() {
  await diagnosticHost({command: "logs_clear"}, 5000);
  $("logs").textContent = "No log entries yet.";
  $("log-status").textContent = "Connected · log readable";
  show("Logs cleared.");
}

async function openLogFolder() {
  const response = await diagnosticHost({command: "logs_open"}, 5000);
  if (response.path) {
    $("log-path").textContent = response.path;
    $("copy-log-path").hidden = false;
  }
  show(response.opened ? "Log folder opened." : "Log folder is ready; copy the path to open it manually.");
}

function startLogAutoRefresh() {
  if (logAutoRefreshTimer) return;
  logAutoRefreshTimer = setInterval(() => {
    if (!document.hidden) refreshLogs().catch(() => {});
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
  const common = {
    task_id: selectedTaskId(),
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

    return await host({
      command: "attachment_finish",
      upload_id: uploadId,
    });
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

$("calendar-link").addEventListener("change", () =>
  messenger.storage.local.set({calendarLink: $("calendar-link").checked})
);
$("attachment-link").addEventListener("change", () =>
  messenger.storage.local.set({attachmentLink: $("attachment-link").checked})
);
$("refresh").addEventListener("click", () => refresh().catch(error => show(error.message)));
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
$("task").addEventListener("change", renderActionState);
for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () => doAction(button.dataset.action).catch(error => show(error.message)));
}
$("add-note").addEventListener("click", () => addNote().catch(error => show(error.message)));
$("attachment").addEventListener("change", event => {
  uploadFiles([...event.target.files]).catch(error => show(error.message));
  event.target.value = "";
});

if (messenger.assistantCalendar?.onTasksChanged) {
  messenger.assistantCalendar.onTasksChanged.addListener(scheduleTaskRefresh);
}

window.addEventListener("pagehide", () => {
  if (logAutoRefreshTimer) {
    clearInterval(logAutoRefreshTimer);
    logAutoRefreshTimer = null;
  }
  if (nativePort) {
    nativePort.disconnect();
    nativePort = null;
  }
  if (diagnosticPort) {
    diagnosticPort.disconnect();
    diagnosticPort = null;
  }
});

$("when").value = localInputNow();
loadSettings()
  .then(async () => {
    // Task/status and logs are independent surfaces. A failure in one must not
    // leave the other permanently stuck at “Loading…”.
    await Promise.allSettled([
      refresh().catch(error => {
        $("bridge-status").textContent = "Core unavailable";
        show(error.message);
      }),
      refreshLogs().catch(() => {}),
    ]);
    startLogAutoRefresh();
  })
  .catch(error => {
    $("bridge-status").textContent = "Core unavailable";
    renderLogError(error);
    show(error.message);
  });
