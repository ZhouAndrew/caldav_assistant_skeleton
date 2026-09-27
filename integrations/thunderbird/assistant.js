const HOST = "local.caldav_assistant";
const ATTACHMENT_CHUNK_BYTES = 256 * 1024;
const $ = (id) => document.getElementById(id);

let nativePort = null;
const nativeWaiters = [];

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
      nativeWaiters.shift().reject(new Error(detail));
    }
  });
  nativePort = port;
  return port;
}

function host(message) {
  return new Promise((resolve, reject) => {
    const port = ensureNativePort();
    nativeWaiters.push({resolve, reject});
    try {
      port.postMessage(message);
    } catch (error) {
      nativeWaiters.pop();
      reject(error);
    }
  });
}

function selectedTaskId() {
  const value = $("task").value;
  if (!value) throw new Error("Choose a task first.");
  return value;
}

function taskLabel(task, state) {
  const marks = [];
  if (state.current_task_id === task.id) marks.push("▶");
  if ((state.paused_task_ids || []).includes(task.id)) marks.push("⏸");
  if (task.status === "COMPLETED") marks.push("✓");
  if (task.status === "CANCELLED") marks.push("×");
  return (marks.length ? marks.join("") + " " : "") + task.summary;
}

async function refresh() {
  const data = await host({command: "snapshot"});
  const select = $("task");
  const old = select.value;
  select.textContent = "";
  for (const task of data.tasks) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = taskLabel(task, data.state);
    select.appendChild(option);
  }
  if (old && data.tasks.some(t => t.id === old)) select.value = old;
  if (!select.value && data.state.current_task_id) select.value = data.state.current_task_id;
  $("bridge-status").textContent = "Core connected";
  $("task-status").textContent = data.state.current_task_id
    ? "Working: " + (data.tasks.find(t => t.id === data.state.current_task_id)?.summary || data.state.current_task_id)
    : "No active work";

  const history = data.history_calendar?.name || "CalDAV Assistant History";
  const lines = data.today || [];
  $("today").textContent = [`History: ${history}`, ...lines].join("\n");
}

async function doAction(action) {
  const taskId = selectedTaskId();
  const response = await host({
    command: "action",
    action,
    task_id: taskId,
    at: isoFromInput(),
    calendar_link: $("calendar-link").checked,
  });
  const wp = response.wordpress;
  show(response.message + (wp?.message ? " · " + wp.message : ""));
  $("when").value = localInputNow();
  await refresh();
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
$("refresh").addEventListener("click", () => refresh().catch(e => show(e.message)));
for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () => doAction(button.dataset.action).catch(e => show(e.message)));
}
$("add-note").addEventListener("click", () => addNote().catch(e => show(e.message)));
$("attachment").addEventListener("change", (event) => {
  uploadFiles([...event.target.files]).catch(e => show(e.message));
  event.target.value = "";
});
window.addEventListener("pagehide", () => {
  if (nativePort) {
    nativePort.disconnect();
    nativePort = null;
  }
});

$("when").value = localInputNow();
loadSettings()
  .then(refresh)
  .catch(error => {
    $("bridge-status").textContent = "Core unavailable";
    show(error.message);
  });
